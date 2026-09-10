import hashlib
import io
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse
import requests
from PIL import Image
from .storage import atomic_write
from .models import ART_TYPES


from difflib import SequenceMatcher


def normalized(name):
    return re.sub(r'[^\w]', '', name.casefold()).replace('_', '')


def title_queries(query):
    """Small spelling variants for launchers that expose the wrong game title.

    The executable is often the only source, so a one-letter word mismatch
    (notably ``Tales`` vs. ``Tails``) must not make an otherwise exact lookup
    fail.  Results are still matched with the normal confidence rules.
    """
    query = re.sub(r'\s+', ' ', str(query or '')).strip()
    variants = [query]
    # Launch folders commonly use a dash where the official Steam title uses
    # a colon. Steam Store search treats those as different queries.
    colon_title = re.sub(r'\s+[-–—]\s+', ': ', query)
    if colon_title != query:
        variants.append(colon_title)
    replacements = ((r'\btales\b', 'tails'), (r'\btails\b', 'tales'))
    for source in list(variants):
        for pattern, replacement in replacements:
            candidate = re.sub(pattern, lambda match: replacement.title() if match.group(0)[0].isupper() else replacement,
                               source, flags=re.I)
            if candidate != source:
                variants.append(candidate)
    return list(dict.fromkeys(item for item in variants if item))


def exact_match(results, name):
    matches = [item for item in results if normalized(item['name']) == normalized(name)]
    if not matches:
        return None
    # SteamGridDB may contain both a Steam-linked and a custom record with the
    # same normalized title. Prefer the verified Steam-linked record.
    matches.sort(key=lambda item: (
        'steam' not in item.get('types', []),
        not item.get('verified', False),
        item.get('id', 0),
    ))
    rank = lambda item: ('steam' not in item.get('types', []), not item.get('verified', False))
    return matches[0] if len(matches) == 1 or rank(matches[0]) < rank(matches[1]) else None


def smart_match(results, name):
    exact = exact_match(results, name)
    if exact:
        return exact
    if not results:
        return None

    target_norm = normalized(name)
    query_nums = re.findall(r'(?i)\b(\d+|ii|iii|iv|v|vi|vii|viii|ix|x)\b', name)
    query_last_num = query_nums[-1].casefold() if query_nums else ''

    candidates = []
    for index, item in enumerate(results):
        item_name = item.get('name', '')
        item_norm = normalized(item_name)
        item_nums = re.findall(r'(?i)\b(\d+|ii|iii|iv|v|vi|vii|viii|ix|x)\b', item_name)
        item_last_num = item_nums[-1].casefold() if item_nums else ''
        if item_last_num != query_last_num and (item_last_num or query_last_num):
            continue

        score = SequenceMatcher(None, target_norm, item_norm).ratio()
        prefix = normalized(re.split(r'[:|\-–—]', item_name)[0])
        if prefix == target_norm:
            if index == 0:
                return item
            score = max(score, 0.92)

        if score >= 0.80:
            candidates.append((score, item))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_item = candidates[0]
    if len(candidates) == 1:
        return best_item
    if best_score - candidates[1][0] >= 0.08:
        return best_item
    return None


def search_names(game):
    """Return useful title queries without trusting one noisy executable field."""
    values = [game.name, *getattr(game, 'search_names', [])]
    if game.source:
        source = Path(game.source)
        values.append(source.stem if source.is_file() else source.name)
    values.append(Path(game.exe).stem)
    blocked = {'game', 'launcher', 'start', 'play', 'launch', 'bootstrap', 'shipping', 'bootstrappackagedgame'}
    result = []
    for value in values:
        value = re.sub(r'\s+', ' ', str(value or '')).strip(' .-_')
        key = normalized(value)
        if len(key) < 3 or key in blocked or any(key == normalized(old) for old in result):
            continue
        result.append(value)
    return result


class Providers:
    def __init__(self, store):
        self.cache = store.root / 'images'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.key = store.secret('sgdb_key')
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'NSLM/0.1 (Windows desktop; Non Steam Library Manager)'

    def request(self, method, url, cancel=None, **kwargs):
        for attempt in range(3):
            if cancel and cancel.is_set():
                raise InterruptedError('Cancelled')
            try:
                response = self.session.request(method, url, timeout=(8, 25), **kwargs)
            except requests.RequestException as error:
                raise RuntimeError('Service unavailable. Check your internet connection.') from error
            if response.status_code == 429 or response.status_code >= 500:
                response.close()
                if cancel:
                    if cancel.wait(1 + attempt * 2):
                        raise InterruptedError('Cancelled')
                else:
                    time.sleep(1 + attempt * 2)
                continue
            if response.status_code in (401, 403):
                response.close()
                raise RuntimeError('API key rejected. Check it in Settings.')
            if not response.ok:
                code = response.status_code
                response.close()
                raise RuntimeError(f'Service returned error {code}. Try again later.')
            return response
        raise RuntimeError('Service is busy. Try again later.')

    def sgdb(self, endpoint, params=None, cancel=None):
        if not self.key:
            raise ValueError('Add your SteamGridDB API key in Settings > Artwork.')
        with self.request('GET', 'https://www.steamgriddb.com/api/v2' + endpoint, cancel=cancel,
                          params=params, headers={'Authorization': 'Bearer ' + self.key}) as response:
            data = response.json()
        if not data.get('success'):
            raise RuntimeError('SteamGridDB request failed')
        return data.get('data', [])

    def search(self, query, cancel=None):
        results = []
        seen = set()
        for candidate in title_queries(query):
            for item in self.sgdb('/search/autocomplete/' + quote(candidate, safe=''), cancel=cancel):
                item_id = item.get('id')
                if item_id not in seen:
                    seen.add(item_id)
                    results.append(item)
        return results

    def steam_store_game(self, name, cancel=None):
        """Find the official Steam game before asking the community gallery."""
        for candidate in title_queries(name):
            with self.request('GET', 'https://store.steampowered.com/api/storesearch/', cancel=cancel,
                              params={'term': candidate, 'l': 'english', 'cc': 'us'}) as response:
                items = response.json().get('items', [])
            match = smart_match(items, candidate)
            if match and str(match.get('id', '')).isdigit():
                return match
        return None

    def steam_store_match(self, name, cancel=None):
        game = self.steam_store_game(name, cancel)
        return int(game['id']) if game else 0

    def steam_store_assets(self, appid, cancel=None):
        """Return exact official CDN URLs, including newer hashed asset paths.

        Older Steam games expose assets at a predictable URL such as
        ``.../apps/<appid>/library_600x900.jpg``.  Newer releases store the
        same files behind a content hash, so guessing the legacy location
        returns 404 even though Steam itself has all of the artwork.  Steam's
        public StoreBrowse response provides that hash without an API key.
        """
        appid = int(appid)
        request = {
            'ids': [{'appid': appid}],
            'context': {'language': 'english', 'country_code': 'US'},
            'data_request': {'include_assets': True},
        }
        with self.request('GET', 'https://api.steampowered.com/IStoreBrowseService/GetItems/v1/', cancel=cancel,
                          params={'input_json': json.dumps(request, separators=(',', ':'))}) as response:
            items = response.json().get('response', {}).get('store_items', [])
        item = next((value for value in items if int(value.get('appid', 0)) == appid and value.get('success')), None)
        assets = item.get('assets', {}) if item else {}
        template = str(assets.get('asset_url_format', ''))
        required = f'steam/apps/{appid}/'
        if not isinstance(assets, dict) or not template.startswith(required) or '${FILENAME}' not in template:
            return {kind: [] for kind in ART_TYPES}

        def official_url(name):
            filename = str(assets.get(name, ''))
            if not filename or filename.startswith(('/', '\\')) or '..' in filename.replace('\\', '/').split('/'):
                return ''
            return 'https://shared.fastly.steamstatic.com/store_item_assets/' + template.replace('${FILENAME}', filename)

        result = {
            'portrait': [official_url(name) for name in ('library_capsule_2x', 'library_capsule', 'hero_capsule_2x', 'hero_capsule')],
            'landscape': [official_url(name) for name in ('library_header_2x', 'library_header', 'header_2x', 'header')],
            'hero': [official_url(name) for name in ('library_hero_2x', 'library_hero', 'hero_capsule_2x', 'hero_capsule')],
            'logo': [official_url(name) for name in ('library_logo_2x', 'library_logo', 'logo')],
            'icon': [],
        }
        icon_hash = str(assets.get('community_icon', ''))
        if re.fullmatch(r'[0-9a-f]{40}', icon_hash):
            result['icon'].append(f'https://shared.fastly.steamstatic.com/community_assets/images/apps/{appid}/{icon_hash}.jpg')
        return {kind: list(dict.fromkeys(url for url in urls if url)) for kind, urls in result.items()}

    @staticmethod
    def is_community_art(source):
        """Whether a saved source is a SteamGridDB choice, not a manual file."""
        return 'steamgriddb.com' in str(source or '').casefold()

    def official_artwork_variants(self, game, kind, cancel=None):
        """Return the distinct official Steam choices for one artwork type.

        SteamDB is useful for inspecting these files, but Steam publishes the
        files themselves. Reading Steam's public metadata avoids page scraping
        and works even when SteamGridDB has no artwork for a matched game.
        """
        official = self.steam_store_game(game.name, cancel)
        if not official:
            return []
        appid = int(official['id'])
        try:
            assets = self.steam_store_assets(appid, cancel)
        except InterruptedError:
            raise
        except Exception:
            assets = {}
        # A 2x file and its ordinary-size companion are the same artwork, so
        # show it once. Different capsule and hero files remain distinct.
        urls = list(assets.get(kind, [])) or self.steam_store_urls(appid, kind)
        seen, result = set(), []
        for url in urls:
            path = urlparse(url).path.casefold().replace('_2x.', '.')
            if path in seen:
                continue
            seen.add(path)
            result.append({
                'id': 'steam:' + hashlib.sha256(url.encode()).hexdigest(),
                'url': url,
                'thumb': url,
                'author': {'name': 'Official Steam'},
                'source': 'Official Steam',
            })
        return result

    def gallery_variants(self, game, kind, page=0, cancel=None):
        """Return official choices first, then paginated SteamGridDB choices."""
        official = self.official_artwork_variants(game, kind, cancel) if page == 0 else []
        if not game.sgdb_id:
            self.sgdb_match(game, cancel)
        community = self.assets(game.sgdb_id, kind, page, cancel) if game.sgdb_id else []
        return official + community

    def sgdb_match(self, game, cancel=None):
        """Resolve SteamGridDB only when official Steam artwork is missing."""
        if game.sgdb_id or not self.key:
            return game.sgdb_id
        for query in search_names(game):
            match = smart_match(self.search(query, cancel), query)
            if match:
                game.sgdb_id = match['id']
                return game.sgdb_id
        return 0

    @staticmethod
    def steam_store_urls(appid, kind):
        base = f'https://cdn.cloudflare.steamstatic.com/steam/apps/{int(appid)}'
        return {
            'portrait': [f'{base}/library_600x900.jpg'],
            'landscape': [f'{base}/library_460x215.jpg', f'{base}/header.jpg'],
            'hero': [f'{base}/library_hero.jpg', f'{base}/header.jpg'],
            'logo': [f'{base}/library_logo.png', f'{base}/logo.png'],
            'icon': [f'{base}/icon.png'],
        }[kind]

    def assets(self, game_id, kind, page=0, cancel=None):
        endpoint = {'portrait': 'grids', 'landscape': 'grids', 'hero': 'heroes', 'logo': 'logos', 'icon': 'icons'}[kind]
        params = {'types': 'static', 'nsfw': 'false', 'humor': 'false', 'page': page}
        if kind == 'portrait':
            params['dimensions'] = '600x900'
        elif kind == 'landscape':
            params['dimensions'] = '460x215,920x430'
        return self.sgdb(f'/{endpoint}/game/{int(game_id)}', params, cancel)

    def download(self, url, cancel=None):
        parsed = urlparse(url)
        if parsed.scheme != 'https':
            raise ValueError('Image URL must use HTTPS')
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + '.png')
        if path.exists():
            return str(path)
        with self.request('GET', url, cancel=cancel, stream=True) as response:
            content = bytearray()
            for chunk in response.iter_content(64 * 1024):
                if cancel and cancel.is_set():
                    raise InterruptedError('Cancelled')
                content.extend(chunk)
                if len(content) > 24 * 1024 * 1024:
                    raise ValueError('Image exceeds 24 MB')
        with Image.open(io.BytesIO(content)) as picture:
            if picture.width * picture.height > 50_000_000:
                raise ValueError('Image is too large')
            picture.load()
            output = io.BytesIO()
            picture.convert('RGBA').save(output, 'PNG')
        atomic_write(path, output.getvalue())
        return str(path)

    def local_image(self, filename):
        data = Path(filename).read_bytes()
        path = self.cache / (hashlib.sha256(data).hexdigest() + '.png')
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 50_000_000:
                raise ValueError('Image is too large')
            out = io.BytesIO()
            image.convert('RGBA').save(out, 'PNG')
        atomic_write(path, out.getvalue())
        return str(path)

    def artwork_set(self, game, cancel, progress, replace=False):
        missing, failures = [], []
        official = self.steam_store_game(game.name, cancel)
        official_appid = int(official['id']) if official else 0
        try:
            official_assets = self.steam_store_assets(official_appid, cancel) if official_appid else {}
        except InterruptedError:
            raise
        except Exception:
            # The legacy CDN paths and SteamGridDB stay available if Steam's
            # metadata service is temporarily unreachable.
            official_assets = {}
        for kind, label in ART_TYPES.items():
            current_source = game.art_sources.get(kind, '')
            # An older SteamGridDB fallback should give way to official Steam
            # artwork, while manual and already-official choices stay intact.
            replace_community_fallback = self.is_community_art(current_source)
            if kind in game.art and not replace and not replace_community_fallback:
                continue
            progress(f'{game.name} · {label.lower()}')
            try:
                urls = list(official_assets.get(kind, []))
                urls += self.steam_store_urls(official_appid, kind) if official_appid else []
                for url in dict.fromkeys(urls):
                    try:
                        game.art[kind] = self.download(url, cancel)
                        game.art_sources[kind] = url
                        break
                    except InterruptedError:
                        raise
                    except Exception:
                        continue
                if kind in game.art:
                    continue
                # Keep the working community fallback if Steam did not have a
                # file for this type. It is better than replacing it with none.
                if current_source and not replace:
                    continue
                sgdb_id = self.sgdb_match(game, cancel)
                items = self.assets(sgdb_id, kind, cancel=cancel) if sgdb_id else []
                if items:
                    best = max(items, key=lambda i: i.get('score', 0))
                    game.art[kind] = self.download(best['url'], cancel)
                    game.art_sources[kind] = best['url']
                else:
                    missing.append(label)
            except InterruptedError:
                raise
            except Exception as error:
                failures.append(f'{label}: {error}')
        game.note = ('Unavailable: ' + ', '.join(missing) if missing else '')
        if failures:
            game.note += ('; ' if game.note else '') + '; '.join(failures)
        return game

    def enrich(self, games, cancel, progress, replace=False):
        import copy
        result = copy.deepcopy(games)
        for index, game in enumerate(result):
            if cancel.is_set():
                raise InterruptedError('Cancelled')
            progress(f'Finding artwork {index + 1}/{len(result)} · {game.name}')
            try:
                self.artwork_set(game, cancel, progress, replace)
                game.pending = True
            except InterruptedError:
                raise
            except Exception as error:
                game.note = str(error)
        return result
