"""One-time migration of 0.1 interface copy to English."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PAIRS = r'''
SteamShelf — игры на своих местах|SteamShelf
ИГРЫ НА СВОИХ МЕСТАХ|STEAM LIBRARY MANAGER
Меньше настроек.\nБольше времени на игры.| 
Добро пожаловать. Начните с папки с играми.|Ready
Ваша библиотека|Library
Любимые игры из разных папок. Вместе в Steam.|Manage non-Steam games and artwork.
Хорошая коллекция начинается с одной папки|Game folders
Найдём игры, подберём оформление и подготовим всё к добавлению.|Add a folder to scan for games.
Поиск по вашей коллекции…|Search games...
Все игры|All games
Уже в Steam|In Steam
Новые|New
Нужна проверка|Review needed
Выбрать видимые|Select visible
Снять выбор|Clear selection
Подобрать оформление|Find artwork
Добавить / обновить|Add / update
Папки с играми|Folders
Сохраним ваши папки и проверим новые игры при следующем запуске.|Manage folders included in scans.
Убрать из списка|Remove
Проверить папки|Scan folders
Windows и Nintendo Switch|Folder types
Для Windows укажите папку, внутри которой лежат папки отдельных игр. Для Switch выберите папку с образами и Eden.exe. Можно добавить несколько источников.\n\nПапки проверяются при запуске и по кнопке Rescan. Игры добавляются в Steam только по вашей команде.|Windows: a folder containing games. Switch: a ROM folder and Eden executable. Scanning never changes Steam.
Можно вернуться назад|Backups
Резервные копии сторонних ярлыков и оформления выбранного профиля Steam.|Back up non-Steam shortcuts and artwork for the selected profile.
Копия перед каждым изменением|Automatic backups
Сохраняются shortcuts.vdf и вся папка grid. Игровые файлы, сохранения и покупки Steam в копию не входят. При восстановлении сначала сохраним текущее состояние.|A backup is created before each Steam update or restore. Backups include shortcuts and artwork, not game files or saves.
Создать копию сейчас|Create backup
Восстановить выбранную|Restore selected
Открыть папку ↗|Open folder
Место для ваших любимых игр|No games to display
Добавьте папку с играми — SteamShelf найдёт подходящие файлы запуска.\nЗдесь также появятся сторонние игры из выбранного профиля Steam.|Add a game folder or select your Steam profile in Settings.
По этому запросу игр нет. Попробуйте другой фильтр.|No matches. Try a different search or filter.
Выбрать папку с играми|Add folder
Отмена после текущего действия…|Cancelling...
Не удалось завершить|Operation failed
Проверка завершена. Новых игр:|Scan complete. New games:
Пропущено папок:|Folder warnings:
Результат проверки|Scan results
Для автоматического оформления добавьте ключ SteamGridDB в настройках.|Add a SteamGridDB API key in Settings to download artwork.
Оформление подготовлено; требуют внимания:|Artwork processed. Items to review:
Оформление подготовлено.|Artwork ready.
Результат подбора|Artwork results
Добавление в Steam|Update Steam
Всё готово к добавлению|Review changes
Профиль Steam:|Steam profile:
Steam закроется на время записи. Сначала создадим резервную копию.|Steam will close during the update. A backup will be created first.
уже в Steam|in Steam
новая игра|new game
Обновить выбранные игры, которые уже есть в Steam|Update selected games already in Steam
Без этой опции существующие записи будут пропущены. Их изображения и настройки сохранятся.|Existing entries are skipped unless this option is enabled.
Принудительно закрыть Steam, если он не отвечает|Force-close Steam if it does not respond
Перед продолжением завершите запущенные игры.|Close running games before continuing.
Добавить в Steam|Update Steam
Готово. Добавлено / обновлено:|Done. Added / updated:
Пропущено:|Skipped:
Настройки сохранены.|Settings saved.
Эта папка уже есть в списке.|This folder is already listed.
Включена|Enabled
Проверка отключена|Disabled
Папка убрана из списка. Файлы игр сохранены.|Folder removed from the list. Game files were not changed.
Создание резервной копии…|Creating backup...
Steam изменил файлы во время копирования. Закройте Steam и повторите.|Steam changed files during backup. Close Steam and try again.
Резервная копия сохранена:|Backup saved:
Резервная копия SteamShelf|SteamShelf backup
Резервная копия (*.zip)|Backup (*.zip)
Восстановить библиотеку?|Restore backup?
Копия:|Backup:
Текущие сторонние ярлыки и оформление профиля|The current shortcuts and artwork for profile
будут заменены содержимым копии. Перед этим сохраним текущее состояние. Steam временно закроется.|will be replaced by this backup. The current state will be backed up first. Steam will close temporarily.
Библиотека восстановлена. Предыдущее состояние также сохранено.|Backup restored. The previous state has also been saved.
Дождитесь завершения операции перед закрытием приложения.|Wait for the current operation or cancel it before closing.
SteamShelf уже запущен.|SteamShelf is already running.
Возникла ошибка:|An error occurred:
Подробности сохранены в error.log.|Details were saved to error.log.
Папка с играми|Game folder
Добавим ваши игры|Add folder
Выберите общую папку с играми или папку одной игры.|Select a folder containing games, or a single game folder.
Компьютерные игры · Windows|Windows games
Тип игр|Type
Аргументы Eden|Eden arguments
Сканировать эту папку|Include in scans
Для Eden: .nsp, .xci и .nro. Эмулятор должен быть уже настроен.\n{rom} автоматически заменяется путём к игре.|Supports .nsp, .xci and .nro. Eden must be configured separately.\n{rom} is replaced with the game path.
Сохранить папку|Save folder
Приложение (*.exe)|Executable (*.exe)
Папка не найдена|Folder not found
Выберите существующую папку с играми.|Select an existing game folder.
Настройка Eden|Eden setup
Выберите EXE эмулятора и оставьте {rom} в аргументах.|Select the emulator executable and include {rom} in the arguments.
Настройки SteamShelf|SteamShelf settings
Всё на своих местах|Settings
Папка Steam|Steam folder
Проверять сохранённые папки при запуске|Scan saved folders on startup
Запускать Steam после добавления|Start Steam after updating
Если Steam уже работал, приложение запустит его снова даже при отключённой опции.|Steam is always restarted if it was running before the update.
Один бесплатный ключ для обложек, фонов, логотипов и иконок.\nВойдите на сайте через Steam и скопируйте свой API key.|Enter your SteamGridDB API key to download artwork.\nSign in on the website with Steam to get a free key.
Открыть страницу ключа ↗|Get API key
Вставьте API key SteamGridDB|SteamGridDB API key
Ключ хранится зашифрованным средствами Windows для вашей учётной записи.|The key is encrypted for your Windows account.
Информация об играх|Metadata
Сохранить настройки|Save settings
Не удалось сохранить|Save failed
Настроить игру ·|Edit game ·
Ваша игра. Ваше оформление.|Game details
Выбрать EXE|Browse
Рабочая папка|Start in
Запись из библиотеки Steam|Existing Steam shortcut
Об игре|Description
Игра и запуск|Launch
Найдите точную игру в SteamGridDB|Search SteamGridDB
Использовать выбранную игру|Use selected game
Совпадение пока не выбрано|No match selected
Найти в базе|Match game
Подобрать весь комплект|Download artwork set
Скачать все варианты|Download all variants
Не выбрано|Not selected
Ещё варианты из базы|Load more
Из файла…|From file...
Один комплект — пять типов изображений. Галерея показывает статичные варианты; двойной щелчок выбирает изображение.|Double-click an image to select it. The gallery shows static artwork.
Изменения попадут в Steam после нажатия «Добавить / обновить» в главном окне.|Use Add / update in the main window to apply these changes to Steam.
Сохранить изменения|Save changes
Останавливаем загрузку… Нажмите «Отмена» после её завершения.|Cancelling download... Close this window when the download stops.
EXE игры|Game executable
Найдено совпадений:|Matches:
Выберите нужную игру.|Select the correct game.
Игра выбрана. Можно подобрать оформление.|Game selected. You can now download artwork.
Комплект готов. Можно сохранить изменения.|Artwork ready. Save to keep your selection.
Текущее изображение|Current artwork
Изображение ещё не выбрано|No artwork selected
Сначала выберите игру в базе.|Select a database match first.
Загрузка вариантов|Loading variants
Варианты загружены. Дважды нажмите на понравившийся.|Double-click an image to select it.
Больше вариантов нет.|No more variants.
изображение выбрано.|image selected.
Выбрать изображение|Choose image
Изображения (*.png *.jpg *.jpeg *.webp *.ico)|Images (*.png *.jpg *.jpeg *.webp *.ico)
сохранено вариантов:|variants downloaded:
В локальный кэш скачано|Downloaded
вариантов всех пяти типов. Выбирайте их через галерею.|variants to the cache. Use the gallery to select them.
Укажите название и существующий EXE.|Enter a name and select an existing executable.
Выберите профиль Steam в настройках|Select a Steam profile in Settings
В выбранной папке не найден steam.exe|steam.exe was not found in the selected folder
Профиль Steam не найден. Войдите в Steam хотя бы один раз.|Steam profile not found. Sign in to Steam first.
Папка профиля перенаправлена за пределы Steam|The profile folder points outside Steam
Папка grid является ссылкой. Для безопасной записи нужна обычная папка.|The grid folder is a directory link. Use a regular folder for writes.
Steam завершает работу…|Closing Steam...
Steam не закрылся за 25 секунд. Завершите игру или закройте Steam вручную. Можно повторить с принудительным завершением Steam.|Steam did not close within 25 seconds. Close your game and Steam, or retry with force-close enabled.
Steam всё ещё работает. Файлы не изменены.|Steam is still running. No files were changed.
Файлы изменились во время резервного копирования. Повторите операцию.|Files changed during backup. Try again.
Резервная копия слишком велика|Backup exceeds the supported size
Некорректная резервная копия|Invalid backup
Резервная копия относится к другому профилю или формату|Backup belongs to a different profile or uses an unsupported format
Состав архива не совпадает с манифестом|Archive contents do not match the manifest
Небезопасный путь в архиве|Unsafe archive path
Контрольная сумма резервной копии не совпадает|Backup checksum mismatch
Другая операция SteamShelf ещё выполняется. Если приложение ранее аварийно завершилось, удалите|Another SteamShelf operation is active. If the app previously crashed, remove
Проверьте название и EXE игры «{game.name}»|Check the name and executable for {game.name}
Подготовка библиотеки и изображений…|Preparing shortcuts and artwork...
Steam запущен снова или библиотека изменилась. Повторите операцию.|Steam restarted or the library changed. Try again.
Сохранение в Steam…|Updating Steam...
Проверка записи не пройдена|Write verification failed
Steam снова запущен. Восстановление отменено.|Steam restarted. Restore cancelled.
Проверка восстановления не пройдена|Restore verification failed
Операция отменена|Cancelled
Сервис недоступен. Проверьте подключение к интернету.|Service unavailable. Check your internet connection.
Сервис отклонил ключ доступа. Проверьте его в настройках.|API key rejected. Check it in Settings.
Сервис вернул ошибку {code}. Повторите позже.|Service returned error {code}. Try again later.
Сервис временно занят. Повторите позже.|Service is busy. Try again later.
Добавьте ключ SteamGridDB в настройках → Обложки.|Add your SteamGridDB API key in Settings > Artwork.
SteamGridDB не смог выполнить запрос|SteamGridDB request failed
Изображение должно использовать HTTPS|Image URL must use HTTPS
Изображение превышает 24 МБ|Image exceeds 24 MB
Изображение слишком большое|Image is too large
Нет в базе:|Unavailable:
Поиск оформления|Finding artwork
Выберите совпадение вручную в редакторе игры|Select a database match in the game editor
Windows не смог прочитать сохранённый ключ. Введите его заново.|Windows could not decrypt the saved key. Enter it again.
Не удалось прочитать {path}. Файл сохранён без изменений: {error}|Could not read {path}. File was not changed: {error}
Обрезанный shortcuts.vdf — запись отменена|Truncated shortcuts.vdf. Write cancelled
Повреждённая строка VDF|Invalid VDF string
Слишком глубокая структура VDF|VDF nesting limit exceeded
Неподдерживаемый тип VDF {kind}. Исходный файл не изменён.|Unsupported VDF type {kind}. Original file was not changed.
Лишние данные после VDF. Запись отменена.|Unexpected trailing VDF data. Write cancelled.
Строка VDF содержит нулевой символ|VDF string contains a null character
Не найдена единственная секция shortcuts|Expected one shortcuts section
Некорректная запись shortcut|Invalid shortcut entry
Название из свойств EXE|Name from executable properties
EXE соответствует названию папки|Executable matches the folder name
Найдены игровые данные Unity|Unity game data found
Игровая сборка Unreal Engine|Unreal Engine game executable
Рядом найдена игровая библиотека Steam API|Steam API library found beside executable
Основной загрузчик Unreal Engine|Unreal Engine launcher
Нет доступа:|Access denied:
Сканирование отменено|Scan cancelled
Папка недоступна:|Folder unavailable:
Сканирование:|Scanning:
Укажите Eden.exe для|Select Eden.exe for
Нет {{rom}} в аргументах эмулятора:|Missing {{rom}} in emulator arguments:
Образ Switch; запуск через Eden|Switch ROM; launch with Eden
Есть несколько похожих EXE — проверьте выбор|Multiple launch candidates; review the selection
Кандидат по структуре папки|Candidate based on folder structure
ОФОРМЛЕНИЕ НЕ ВЫБРАНО|NO ARTWORK
Готово к добавлению|Ready to add
Изменения готовы к записи|Pending changes
Библиотека|Library
Резервные копии|Backups
Настройки|Settings
Отменить|Cancel
Отмена|Cancel
Добавить папку|Add folder
Выбрано:|Selected:
сторонних игр в Steam:|non-Steam games:
требуют проверки|to review
изображений|images
игр|games
новых|new
МБ|MB
Профиль|Profile
Обзор|Browse
Обложки|Artwork
Обложка|Cover
Карточка|Grid
Логотип|Logo
Иконка|Icon
Фон|Hero
Название|Name
Запуск|Executable
Аргументы|Arguments
Распознавание|Detection
Найти|Search
Выбрать|Select
Оформление|Artwork
Настроить|Edit
Папка|Folder
В Steam|In Steam
'''
mapping = dict(line.split('|', 1) for line in PAIRS.splitlines() if '|' in line)
for path in (ROOT / 'shelf').glob('*.py'):
    text = path.read_text('utf-8')
    for before, after in sorted(mapping.items(), key=lambda pair: -len(pair[0])):
        text = text.replace(before, after)
    path.write_text(text, 'utf-8')
