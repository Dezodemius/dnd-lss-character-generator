# lss-character

Скилл для Claude: описываешь персонажа D&D 5e (или кидаешь анкету игрока и картинку), Claude
задаёт пару вопросов и отдаёт файл `.json`, который импортируется в
[Long Story Short](https://longstoryshort.app) и сразу работает: характеристики, навыки, хиты,
оружие, магические предметы с бонусами, счётчики умений, заклинания и портрет.

## Установка

Скачай `lss-character.skill` из последнего [релиза](../../releases/latest).

**Claude.ai (сайт и приложение).** Settings -> Capabilities -> Skills -> Upload skill, выбрать
файл `lss-character.skill`. Должно быть включено выполнение кода (Code execution).

**Claude Code.** Распаковать архив (это обычный zip) в папку скиллов:

- Windows: `%USERPROFILE%\.claude\skills\`
- macOS / Linux: `~/.claude/skills/`

Должна получиться папка `.claude/skills/lss-character/` с файлом `SKILL.md` внутри.
Нужен Python 3.8+; желательно `pip install jsonschema pillow`.

## Как пользоваться

Просто попроси в чате, например:

- «Сделай лист для LSS: тифлинг-колдун 3 уровня, бывший цирковой акробат»
- «Сгенерируй лист персонажа по анкете» + текст анкеты + картинка
- «Перенеси моего паладина 5 уровня в Long Story Short», дальше описание

Готовый файл загружается в LSS через импорт персонажа из .json.

Что стоит знать:

- Заклинания берутся из SRD и находятся в LSS сами. Заклинания не из SRD (Hex, Booming Blade,
  всё из книг Таши и Ксанатара) появятся, только если добавить их в свой Гримуар.
- Портрет встраивается прямо в файл. Если вдруг не отобразился, загрузи картинку кнопкой
  аватара на листе.
- Вместе с листом Claude отдаёт черновик `*.draft.json`: на новом уровне попроси поправить его
  и пересобрать лист.

## Разработка

```
lss-character/          сам скилл - то, что попадает в архив
  SKILL.md              инструкция для Claude
  scripts/lss.py        сборка черновика в лист и проверка
  reference/            схема LSS, справочники заклинаний SRD, формат черновика
  templates/            пример черновика и готовые листы
tests/fixtures/         черновики для смоук-тестов (*.ok - должны собраться, *.bad - отклониться)
tools/check.py          смоук-тесты
tools/package.py        сборка dist/lss-character.skill
```

```bash
pip install jsonschema pillow
python tools/check.py
python tools/package.py
```

Чтобы Claude Code на своей машине пользовался скиллом прямо из репозитория, свяжи папку
ссылкой, а не копией:

```powershell
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\lss-character" -Target "<путь к репозиторию>\lss-character"
```

Схему и справочники LSS обновляет `python lss-character/scripts/lss.py refresh`.

### Релиз

Тег вида `v*` запускает `.github/workflows/release.yml`: смоук-тесты, сборка архива и релиз
на GitHub с `lss-character.skill` и его sha256.

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Источники

Схема листа и справочники заклинаний SRD в `lss-character/reference/` взяты из открытой
документации для разработчиков Long Story Short:
https://longstoryshort.app/doc/developers/characters/. Проект не связан с командой LSS.
Материалы SRD 5.1 / 5.2 распространяются по лицензии CC-BY-4.0 (Wizards of the Coast).
