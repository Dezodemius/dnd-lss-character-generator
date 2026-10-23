# Copyright 2026 Egor Gladkov (Dezodemius), https://github.com/Dezodemius/dnd-lss-character-generator
# SPDX-License-Identifier: Apache-2.0

"""Сборка и проверка листа персонажа Long Story Short (LSS).

Команды:
  build <draft.json> [-o out.json]   черновик -> готовый файл импорта LSS + проверка
  validate <file.json>               проверить готовый файл (свой или экспорт из LSS)
  spells --edition 2014 [--class wizard] [--level 1] [--max-level 3] [--search огн]
  refresh                            скачать свежие схему и справочники с longstoryshort.app

Черновик - удобная для модели форма листа (см. SKILL.md и templates/draft-template.json):
простые значения вместо обёрток { name, value }, текст строками, заклинания по-русски или слагами.
Скрипт приводит его к строгому формату, резолвит заклинания по справочнику SRD и проверяет
результат официальной JSON Schema плюс перекрёстными проверками, которые схема не ловит.
"""

import argparse
import copy
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REF_DIR = SKILL_DIR / "reference"
SCHEMA_PATH = REF_DIR / "character.schema.json"

REMOTE = {
    "character.schema.json": "https://longstoryshort.app/schema/v1/character.json",
    "character-example.data.json": "https://longstoryshort.app/schema/v1/character-example.json",
    "srd-spell-slugs-2014.json": "https://longstoryshort.app/datasets/srd-spell-slugs-2014.json",
    "srd-spell-slugs-2024.json": "https://longstoryshort.app/datasets/srd-spell-slugs-2024.json",
}

ABILITIES = ["str", "dex", "con", "int", "wis", "cha"]

ABILITY_ALIASES = {
    "сила": "str", "сил": "str", "strength": "str",
    "ловкость": "dex", "лов": "dex", "dexterity": "dex",
    "телосложение": "con", "тел": "con", "constitution": "con",
    "интеллект": "int", "инт": "int", "intelligence": "int",
    "мудрость": "wis", "мдр": "wis", "муд": "wis", "wisdom": "wis",
    "харизма": "cha", "хар": "cha", "charisma": "cha",
}

SKILLS = {
    "athletics": "str",
    "acrobatics": "dex", "sleight of hand": "dex", "stealth": "dex",
    "arcana": "int", "history": "int", "investigation": "int", "nature": "int", "religion": "int",
    "animal handling": "wis", "insight": "wis", "medicine": "wis", "perception": "wis", "survival": "wis",
    "deception": "cha", "intimidation": "cha", "performance": "cha", "persuasion": "cha",
}
AIME_SKILLS = {"riddle": "int", "shadow-lore": "wis"}

SKILL_ALIASES = {
    "атлетика": "athletics", "акробатика": "acrobatics", "ловкость рук": "sleight of hand",
    "скрытность": "stealth", "магия": "arcana", "история": "history", "анализ": "investigation",
    "расследование": "investigation", "природа": "nature", "религия": "religion",
    "уход за животными": "animal handling", "обращение с животными": "animal handling",
    "проницательность": "insight", "медицина": "medicine", "восприятие": "perception",
    "внимательность": "perception", "выживание": "survival", "обман": "deception",
    "запугивание": "intimidation", "выступление": "performance", "убеждение": "persuasion",
}

INFO_WRAPPED = ["charClass", "charSubclass", "level", "background", "playerName", "race", "alignment", "experience"]
SUBINFO_KEYS = ["age", "height", "weight", "eyes", "skin", "hair"]

CLASS_ALIASES = {
    "barbarian": "barbarian", "варвар": "barbarian",
    "bard": "bard", "бард": "bard",
    "cleric": "cleric", "жрец": "cleric", "клирик": "cleric",
    "druid": "druid", "друид": "druid",
    "fighter": "fighter", "воин": "fighter", "боец": "fighter",
    "monk": "monk", "монах": "monk",
    "paladin": "paladin", "паладин": "paladin",
    "ranger": "ranger", "следопыт": "ranger", "рейнджер": "ranger",
    "rogue": "rogue", "плут": "rogue",
    "sorcerer": "sorcerer", "чародей": "sorcerer",
    "warlock": "warlock", "колдун": "warlock",
    "wizard": "wizard", "волшебник": "wizard", "маг": "wizard",
}
DATASET_CLASSES = set(CLASS_ALIASES.values())

CLASS_HIT_DIE = {
    "barbarian": "d12", "fighter": "d10", "paladin": "d10", "ranger": "d10",
    "bard": "d8", "cleric": "d8", "druid": "d8", "monk": "d8", "rogue": "d8", "warlock": "d8",
    "artificer": "d8", "sorcerer": "d6", "wizard": "d6",
}
CLASS_SAVES = {
    "barbarian": ["str", "con"], "bard": ["dex", "cha"], "cleric": ["wis", "cha"], "druid": ["int", "wis"],
    "fighter": ["str", "con"], "monk": ["str", "dex"], "paladin": ["wis", "cha"], "ranger": ["str", "dex"],
    "rogue": ["dex", "int"], "sorcerer": ["con", "cha"], "warlock": ["wis", "cha"], "wizard": ["int", "wis"],
    "artificer": ["con", "int"],
}
CLASS_CAST_ABILITY = {
    "bard": "cha", "cleric": "wis", "druid": "wis", "paladin": "cha", "ranger": "wis",
    "sorcerer": "cha", "warlock": "cha", "wizard": "int", "artificer": "int",
}
FULL_CASTERS = {"bard", "cleric", "druid", "sorcerer", "wizard"}
HALF_CASTERS = {"paladin", "ranger"}

# Ячейки полного заклинателя по уровню (одинаковы в 2014 и 2024).
FULL_SLOTS = [
    [], [2], [3], [4, 2], [4, 3], [4, 3, 2], [4, 3, 3], [4, 3, 3, 1], [4, 3, 3, 2], [4, 3, 3, 3, 1],
    [4, 3, 3, 3, 2], [4, 3, 3, 3, 2, 1], [4, 3, 3, 3, 2, 1], [4, 3, 3, 3, 2, 1, 1], [4, 3, 3, 3, 2, 1, 1],
    [4, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 2, 1, 1, 1, 1],
    [4, 3, 3, 3, 3, 1, 1, 1, 1], [4, 3, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 3, 2, 2, 1, 1],
]

# Ячейки договора колдуна: (количество, круг).
PACT_SLOTS = [
    (0, 0), (1, 1), (2, 1), (2, 2), (2, 2), (2, 3), (2, 3), (2, 4), (2, 4), (2, 5), (2, 5),
    (3, 5), (3, 5), (3, 5), (3, 5), (3, 5), (3, 5), (4, 5), (4, 5), (4, 5), (4, 5),
]

PROF_KEYS = ["armor-light", "armor-medium", "armor-heavy", "armor-label", "weapon-simple", "weapon-martial", "weapon-other"]
PROF_ALIASES = {
    "shield": "armor-label", "shields": "armor-label", "щит": "armor-label", "щиты": "armor-label",
    "light": "armor-light", "лёгкие доспехи": "armor-light", "легкие доспехи": "armor-light",
    "medium": "armor-medium", "средние доспехи": "armor-medium",
    "heavy": "armor-heavy", "тяжёлые доспехи": "armor-heavy", "тяжелые доспехи": "armor-heavy",
    "simple": "weapon-simple", "простое оружие": "weapon-simple",
    "martial": "weapon-martial", "воинское оружие": "weapon-martial",
    "other": "weapon-other", "другое оружие": "weapon-other",
}

TEXT_NODE_TYPES = {
    "doc", "paragraph", "text", "bulletList", "orderedList", "listItem", "roller", "formula", "resource",
    "divider", "spoiler", "spoilerSummary", "spoilerContent", "taskList", "taskItem",
}
TEXT_MARKS = {"bold", "italic", "underline", "link"}

NUMERIC_VARS = {"STR", "DEX", "CON", "INT", "WIS", "CHA", "PROF", "LVL"}
ROLL_VARS = NUMERIC_VARS | {"HALF_PROF"}
FORMULA_FUNCS = {"floor", "ceil", "round", "abs", "max", "min", "pow", "sqrt"}


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.notes = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    def note(self, msg):
        self.notes.append(msg)


class IdGen:
    def __init__(self):
        self.base = int(time.time() * 1000)
        self.n = 0

    def __call__(self, prefix):
        self.n += 1
        return f"{prefix}-{self.base + self.n}"


def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def norm(s):
    return re.sub(r"\s+", " ", str(s).strip().lower().replace("ё", "е"))


def slugify(s):
    s = str(s).lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def has_cyrillic(s):
    return bool(re.search(r"[а-яё]", str(s), re.I))


def ability_code(v):
    if v is None:
        return None
    s = norm(v)
    if s in ABILITIES or s == "none":
        return s
    return ABILITY_ALIASES.get(s)


def class_id_of(info):
    cc = info.get("charClass") or {}
    cid = cc.get("id")
    if cid:
        return cid
    value = norm(cc.get("value", ""))
    if value in ("artificer", "изобретатель"):
        return "artificer"
    for word in re.split(r"[\s/,()]+", value):
        if word in CLASS_ALIASES:
            return CLASS_ALIASES[word]
    return None


def level_of(data):
    try:
        return int(((data.get("info") or {}).get("level") or {}).get("value") or 1)
    except (TypeError, ValueError):
        return 1


# ---------------------------------------------------------------- справочник заклинаний

class SpellIndex:
    def __init__(self, edition):
        self.edition = edition
        self.items = load_json(REF_DIR / f"srd-spell-slugs-{edition}.json")
        self.by_key = {}
        for sp in self.items:
            name = sp["name"]
            m = re.match(r"^(.*?)\s*\[(.+)\]\s*$", name)
            ru, en = (m.group(1), m.group(2)) if m else (name, "")
            for key in (sp["slug"], sp["id"], name, ru, en, slugify(en)):
                if key:
                    self.by_key.setdefault(norm(key), sp)
        self.by_id = {sp["id"]: sp for sp in self.items}

    def resolve(self, ref):
        ref = str(ref).strip()
        hit = self.by_key.get(norm(ref))
        if hit:
            return hit
        m = re.match(r"^(.*?)\s*\[(.+)\]\s*$", ref)
        if m:
            return self.by_key.get(norm(m.group(2))) or self.by_key.get(norm(m.group(1)))
        return self.by_key.get(slugify(ref))


# ---------------------------------------------------------------- текст -> документ редактора

def inline_nodes(text):
    nodes = []
    for i, part in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        if not part:
            continue
        node = {"type": "text", "text": part}
        if i % 2 == 1:
            node["marks"] = [{"type": "bold"}]
        nodes.append(node)
    return nodes


def paragraph(text):
    content = inline_nodes(text)
    return {"type": "paragraph", "content": content} if content else {"type": "paragraph"}


def resource_paragraph(res_id, block_key):
    return {"type": "paragraph", "content": [{"type": "resource", "attrs": {"id": res_id, "textName": block_key}}]}


def text_to_doc(text, block_key):
    lines = text if isinstance(text, list) else str(text).split("\n")
    content = []
    lst = None
    for raw in lines:
        line = str(raw).rstrip()
        bullet = re.match(r"^\s*[-*•]\s+(.*)$", line)
        ordered = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        kind = "bulletList" if bullet else "orderedList" if ordered else None
        if kind:
            if not lst or lst["type"] != kind:
                lst = {"type": kind, "content": []}
                content.append(lst)
            lst["content"].append({"type": "listItem", "content": [paragraph((bullet or ordered).group(1))]})
            continue
        lst = None
        if not line.strip():
            continue
        res = re.match(r"^\s*\[\[resource:([^\]]+)\]\]\s*$", line)
        if res:
            content.append(resource_paragraph(res.group(1).strip(), block_key))
            continue
        heading = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if heading:
            content.append({"type": "paragraph", "content": [{"type": "text", "text": heading.group(1), "marks": [{"type": "bold"}]}]})
            continue
        content.append(paragraph(line))
    if not content:
        content.append({"type": "paragraph"})
    return {"type": "doc", "content": content}


def normalize_text_block(key, v):
    if isinstance(v, (str, list)):
        return {"value": {"data": text_to_doc(v, key)}}
    if isinstance(v, dict):
        if v.get("type") == "doc":
            return {"value": {"data": v}}
        if "data" in v and "value" not in v:
            return {"value": {"data": v["data"]}}
        if "value" in v:
            block = dict(v)
            inner = block["value"]
            if isinstance(inner, (str, list)):
                block["value"] = {"data": text_to_doc(inner, key)}
            elif isinstance(inner, dict) and inner.get("type") == "doc":
                block["value"] = {"data": inner}
            return block
        if "text" in v:
            block = {k: x for k, x in v.items() if k != "text"}
            block["value"] = {"data": text_to_doc(v["text"], key)}
            return block
    return v


def walk_nodes(node, fn, path):
    if not isinstance(node, dict):
        return
    fn(node, path)
    for i, child in enumerate(node.get("content") or []):
        walk_nodes(child, fn, f"{path}.content[{i}]")


# ---------------------------------------------------------------- черновик -> data

def wrap_value(v):
    if isinstance(v, dict):
        return v
    return {"value": v}


def wrap_named(key, v):
    if isinstance(v, dict):
        out = dict(v)
        out["name"] = key
        return out
    return {"name": key, "value": v}


def normalize_info(data, rep):
    info = data.setdefault("info", {})
    if not isinstance(info, dict):
        rep.error("info должен быть объектом")
        return
    for key in INFO_WRAPPED:
        default = 1 if key == "level" else ""
        info[key] = wrap_named(key, info.get(key, default))
    for key in ("size", "subrace"):
        if key in info and not isinstance(info[key], dict):
            info[key] = {"value": info[key]}
    if "size" in info:
        info["size"]["value"] = norm(info["size"]["value"])
    else:
        info["size"] = {"value": "medium"}
    lvl = info["level"]["value"]
    if isinstance(lvl, str) and lvl.strip().isdigit():
        info["level"]["value"] = int(lvl)
    xp = info["experience"]["value"]
    if isinstance(xp, str) and xp.strip():
        digits = re.sub(r"\D", "", xp)
        info["experience"]["value"] = int(digits) if digits else ""
    cid = class_id_of(info)
    if cid in DATASET_CLASSES and not info["charClass"].get("id"):
        info["charClass"]["id"] = cid
        rep.note(f"info.charClass.id = {cid} (по названию класса)")


def normalize_stats(data, rep):
    stats = data.get("stats") or {}
    out = {}
    for k, v in stats.items():
        code = ability_code(k) or k
        if isinstance(v, dict):
            v = dict(v)
            v["name"] = code
            out[code] = v
        else:
            out[code] = {"name": code, "score": v}
    for a in ABILITIES:
        if a not in out:
            rep.error(f"stats.{a}: не задано значение характеристики")
    data["stats"] = out


def normalize_saves(data, rep, cid):
    raw = data.get("saves")
    if raw is None:
        raw = CLASS_SAVES.get(cid, [])
        if raw:
            rep.note(f"спасброски взяты по классу {cid}: {', '.join(raw)}")
    out = {a: {"name": a, "isProf": False} for a in ABILITIES}
    if isinstance(raw, list):
        for k in raw:
            code = ability_code(k)
            if code:
                out[code]["isProf"] = True
            else:
                rep.error(f"saves: неизвестная характеристика «{k}»")
    elif isinstance(raw, dict):
        for k, v in raw.items():
            code = ability_code(k) or k
            entry = dict(v) if isinstance(v, dict) else {"isProf": v}
            entry["name"] = code
            entry.setdefault("isProf", False)
            out[code] = entry
    data["saves"] = out


def skill_key(k):
    s = norm(k).replace("_", " ")
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    if s in SKILLS or s in AIME_SKILLS:
        return s
    if s.replace(" ", "") in ("sleightofhand",):
        return "sleight of hand"
    if s.replace(" ", "") in ("animalhandling",):
        return "animal handling"
    if s in ("shadow lore",):
        return "shadow-lore"
    return SKILL_ALIASES.get(s)


def normalize_skills(data, rep):
    raw = data.get("skills") or {}
    out = {k: {"name": k, "baseStat": b} for k, b in SKILLS.items()}
    items = [(k, 1) for k in raw] if isinstance(raw, list) else list(raw.items())
    for k, v in items:
        key = skill_key(k)
        if not key:
            rep.error(f"skills: неизвестный навык «{k}»")
            continue
        base = SKILLS.get(key) or AIME_SKILLS[key]
        entry = dict(v) if isinstance(v, dict) else {"isProf": v}
        entry["name"] = key
        entry["baseStat"] = base
        out[key] = entry
    data["skills"] = out


def normalize_vitality(data, rep, cid, level):
    vit = data.get("vitality") or {}
    out = {}
    for k, v in vit.items():
        if k in ("isDying", "deathFails", "deathSuccesses", "hp-dice-multi"):
            out[k] = v
        elif k == "shield":
            out[k] = {"value": bool(v), "mod": "2"} if isinstance(v, bool) else v
        else:
            out[k] = wrap_value(v)
    for k in ("ac", "speed", "initiative"):
        if k in out and isinstance(out[k].get("value"), (int, float)) and not isinstance(out[k]["value"], bool):
            out[k]["value"] = str(out[k]["value"])
    if "shield" in out and isinstance(out["shield"].get("mod"), (int, float)):
        out["shield"]["mod"] = str(out["shield"]["mod"])
    if "hp-max" not in out:
        rep.error("vitality.hp-max: не задан максимум хитов")
    out.setdefault("hp-max-bonus", {"value": 0})
    out.setdefault("hp-temp", {"value": 0})
    if "hp-current" not in out and "hp-max" in out:
        out["hp-current"] = {"value": out["hp-max"]["value"]}
    if "hit-die" not in out:
        die = CLASS_HIT_DIE.get(cid)
        if die:
            out["hit-die"] = {"value": die}
        else:
            rep.error("vitality.hit-die: не задана кость хитов (класс не распознан)")
    out.setdefault("hp-dice-current", {"value": level})
    out.setdefault("hp-dice-multi", {})
    out.setdefault("darkvision", {"value": 0})
    out.setdefault("speed", {"value": "30"})
    out.setdefault("ac", {"value": "10+[DEX]"})
    out.setdefault("shield", {"value": False, "mod": "2"})
    out.setdefault("initiative", {"value": None})
    out.setdefault("isDying", False)
    out.setdefault("deathFails", 0)
    out.setdefault("deathSuccesses", 0)
    data["vitality"] = out


def normalize_spells_info(data, rep, cid):
    si = data.get("spellsInfo")
    if si is None and cid not in CLASS_CAST_ABILITY:
        return
    si = dict(si or {})
    ability = si.pop("ability", None)
    out = {}
    for k, v in si.items():
        out[k] = wrap_named(k, v) if k in ("base", "save", "mod") else v
    if "base" not in out:
        code = ability_code(ability) or CLASS_CAST_ABILITY.get(cid)
        if code:
            out["base"] = {"name": "base", "value": "", "code": code}
    out.setdefault("save", {"name": "save", "value": ""})
    out.setdefault("mod", {"name": "mod", "value": ""})
    data["spellsInfo"] = out


def slot_table(data, rep, cid, level, edition, subclass_third):
    if "spells" in data or "spellsPact" in data:
        return
    if "/" in str(data["info"]["charClass"]["value"]):
        rep.warn("похоже на мультикласс - ячейки не считаются автоматически, задай data.spells / data.spellsPact явно")
        return
    slots, pact = [], None
    if cid in FULL_CASTERS:
        slots = FULL_SLOTS[level]
    elif cid in HALF_CASTERS or cid == "artificer":
        round_up = edition == "2024" or cid == "artificer"
        eff = (level + 1) // 2 if round_up else level // 2
        slots = FULL_SLOTS[eff] if eff else []
    elif subclass_third:
        eff = level // 3
        slots = FULL_SLOTS[eff] if eff else []
    elif cid == "warlock":
        pact = PACT_SLOTS[level]
    else:
        return
    data["spells"] = {f"slots-{i + 1}": {"value": n, "filled": 0} for i, n in enumerate(slots)}
    data["spellsPact"] = {}
    if pact and pact[0]:
        data["spellsPact"] = {f"slots-{pact[1]}": {"value": pact[0], "filled": 0}}
    rep.note("ячейки заклинаний посчитаны по таблице класса")


def normalize_slots(data):
    for key in ("spells", "spellsPact"):
        raw = data.get(key)
        if not isinstance(raw, dict):
            continue
        out = {}
        for k, v in raw.items():
            name = k if str(k).startswith("slots-") else f"slots-{k}"
            out[name] = {"value": v, "filled": 0} if isinstance(v, (int, float)) else v
        data[key] = out


def normalize_lists(data, rep, ids):
    weapons = []
    for w in data.get("weaponsList") or []:
        w = dict(w)
        w.setdefault("id", ids("weapon"))
        for k in ("name", "dmg", "dmgType", "notes"):
            if k in w and not isinstance(w[k], dict):
                w[k] = {"value": str(w[k])}
        w["ability"] = ability_code(w.get("ability", "str")) or w.get("ability")
        w.setdefault("isProf", True)
        if "notes" in w:
            w.setdefault("notesVisibility", True)
        weapons.append(w)
    data["weaponsList"] = weapons

    att = []
    for a in data.get("attunementsList") or []:
        if isinstance(a, str):
            a = {"value": a}
        a = dict(a)
        a.setdefault("id", ids("attunement"))
        a.setdefault("checked", True)
        att.append(a)
    data["attunementsList"] = att

    effects = []
    for e in data.get("effects") or []:
        e = dict(e)
        e.setdefault("id", ids("effect"))
        effects.append(e)
    if effects:
        data["effects"] = effects

    bonuses = []
    for b in data.get("bonuses") or []:
        b = dict(b)
        b.setdefault("id", ids("bonus"))
        b.setdefault("mode", "add")
        src = b.get("source")
        if src is None:
            b["source"] = {"kind": "user"}
        elif isinstance(src, str):
            b["source"] = {"kind": "item", "label": src}
        b.setdefault("label", b["source"].get("label") or b.get("target", "бонус"))
        if isinstance(b.get("value"), str):
            b["expr"] = b.pop("value")
        bonuses.append(b)
    data["bonuses"] = bonuses

    coins = data.get("coins") or {}
    denoms = ["gp", "sp", "cp"] if str(data.get("template", "")).startswith("aime") else ["gp", "sp", "cp", "pp", "ep"]
    data["coins"] = {d: wrap_value(coins.get(d, 0)) for d in denoms}
    for d in coins:
        if d not in denoms:
            rep.error(f"coins.{d}: такого номинала нет у шаблона")

    prof = data.get("prof") or {}
    if isinstance(prof, list):
        out = {}
        for p in prof:
            key = p if p in PROF_KEYS else PROF_ALIASES.get(norm(p))
            if key:
                out[key] = {"value": True}
            else:
                rep.error(f"prof: неизвестное владение «{p}» (допустимо {', '.join(PROF_KEYS)})")
        prof = out
    else:
        prof = {k: wrap_value(v) for k, v in prof.items()}
    data["prof"] = prof


def normalize_resources(data, rep, ids):
    raw = data.get("resources") or {}
    items = list(raw.values()) if isinstance(raw, dict) else list(raw)
    keys = list(raw.keys()) if isinstance(raw, dict) else [None] * len(items)
    text = data.setdefault("text", {})
    referenced = {}
    for key, block in text.items():
        doc = ((block.get("value") or {}).get("data")) if isinstance(block, dict) else None

        def collect(node, _path, key=key):
            if node.get("type") == "resource":
                referenced[(node.get("attrs") or {}).get("id")] = key

        if isinstance(doc, dict):
            walk_nodes(doc, collect, "")
    out = {}
    for key, r in zip(keys, items):
        r = dict(r)
        r.setdefault("id", key or ids("resource"))
        if "max" in r and isinstance(r["max"], str):
            r["maxExpr"] = r.pop("max")
        if "current" not in r:
            r["current"] = r["max"] if isinstance(r.get("max"), (int, float)) else 0
        r.setdefault("isShortRest", False)
        r.setdefault("isLongRest", False)
        if "location" not in r:
            r["location"] = referenced.get(r["id"], "traits")
        loc = r["location"]
        if r["id"] not in referenced:
            if loc not in text:
                text[loc] = {"value": {"data": {"type": "doc", "content": []}}}
            text[loc]["value"]["data"].setdefault("content", []).append(resource_paragraph(r["id"], loc))
            rep.note(f"виджет ресурса «{r['name']}» добавлен в конец блока text.{loc}")
        out[r["id"]] = r
    data["resources"] = out


def normalize_spellbook(draft, data, rep, edition):
    idx = SpellIndex(edition)
    raw = draft.get("spells") or {}
    if isinstance(raw, list):
        raw = {"prepared": raw}
    book = {"mode": raw.get("mode", "cards"), "prepared": [], "book": [],
            "granted": raw.get("granted", []), "slotless": raw.get("slotless", [])}
    for lst in ("prepared", "book"):
        seen = set()
        for ref in raw.get(lst, []):
            sp = idx.resolve(ref)
            if sp:
                value = sp["id"]
            elif has_cyrillic(ref):
                rep.error(f"spells.{lst}: «{ref}» не найдено в SRD {edition}. Русское имя сервер не сведёт - "
                          "дай английское имя или слаг, или убери заклинание")
                continue
            else:
                value = slugify(re.sub(r"^.*\[(.+)\]\s*$", r"\1", str(ref)))
                rep.warn(f"spells.{lst}: «{ref}» нет в SRD {edition} - оставлено слагом «{value}». Лист найдёт его, "
                         "только если оно есть в гримуаре игрока")
            if value not in seen:
                seen.add(value)
                book[lst].append(value)
    si = data.get("spellsInfo")
    if isinstance(si, dict):
        for key in ("charges", "abilities"):
            if isinstance(si.get(key), dict):
                fixed = {}
                for ref, v in si[key].items():
                    sp = idx.resolve(ref)
                    fixed[sp["id"] if sp else ref] = ability_code(v) if key == "abilities" else v
                si[key] = fixed
    return book


def avatar_from_file(path, base_dir, rep):
    # LSS хранит аватар ссылками на свой сервер, а загрузка туда требует входа в аккаунт.
    # Поэтому картинка встраивается data-URI: приложение подставляет строку прямо в src.
    try:
        from PIL import Image
    except ImportError:
        rep.warn("avatar: Pillow не установлен (pip install pillow) - лист собран без портрета, "
                 "его можно загрузить кнопкой аватара на листе")
        return None
    import base64
    import io
    p = Path(path)
    if not p.is_absolute():
        p = base_dir / p
    if not p.exists():
        rep.error(f"avatar: файл {p} не найден")
        return None
    im = Image.open(p).convert("RGB")
    im.thumbnail((512, 512), Image.LANCZOS)
    out = {}
    for key, fmt, quality in (("jpeg", "JPEG", 82), ("webp", "WEBP", 80)):
        buf = io.BytesIO()
        im.save(buf, fmt, quality=quality)
        out[key] = f"data:image/{key};base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    size_kb = (len(out["jpeg"]) + len(out["webp"])) // 1024
    rep.note(f"avatar встроен из {p.name} ({im.size[0]}x{im.size[1]}, ~{size_kb} КБ)")
    return out


def build(draft, rep, base_dir=Path(".")):
    draft = copy.deepcopy(draft)
    if "data" not in draft:
        draft = {"data": draft}
    edition = str(draft.get("edition") or "")
    if edition not in ("2014", "2024"):
        rep.warn("edition не задан или неверен - взят 2024 (умолчание LSS)")
        edition = "2024"
    sheet_edition = str(draft.get("sheetEdition") or edition)
    data = draft["data"]
    ids = IdGen()

    data["jsonType"] = "character"
    data.setdefault("template", "default")
    if not isinstance(data.get("name"), dict):
        data["name"] = {"value": str(data.get("name", ""))}

    normalize_info(data, rep)
    cid = class_id_of(data["info"])
    level = level_of(data)
    if "subInfo" in data:
        data["subInfo"] = {k: wrap_named(k, v) for k, v in data["subInfo"].items()}
    data.setdefault("proficiency", 2 + (max(level, 1) - 1) // 4)
    normalize_stats(data, rep)
    normalize_saves(data, rep, cid)
    normalize_skills(data, rep)
    normalize_vitality(data, rep, cid, level)
    normalize_spells_info(data, rep, cid)
    sub = norm(data["info"]["charSubclass"]["value"])
    third = any(w in sub for w in ("eldritch knight", "мистический рыцарь", "arcane trickster", "мистический ловкач", "арканный ловкач"))
    slot_table(data, rep, cid, max(1, min(level, 20)), edition, third)
    normalize_slots(data)
    normalize_lists(data, rep, ids)
    data["text"] = {k: normalize_text_block(k, v) for k, v in (data.get("text") or {}).items()}
    normalize_resources(data, rep, ids)
    data.setdefault("conditions", [])
    data.setdefault("exhaustion", 0)
    data.setdefault("inspiration", False)
    if isinstance(data.get("avatar"), str):
        data["avatar"] = avatar_from_file(data["avatar"], base_dir, rep)
    data.setdefault("avatar", None)

    spellbook = normalize_spellbook(draft, data, rep, edition)
    envelope = {
        "jsonType": "character",
        "version": "2",
        "edition": edition,
        "sheetEdition": sheet_edition,
        "spells": spellbook,
        "disabledBlocks": draft.get("disabledBlocks") or {k: [] for k in (
            "info-left", "info-right", "subinfo-left", "subinfo-right", "notes-left", "notes-right")},
    }
    return envelope, data


# ---------------------------------------------------------------- проверки

def check_formula(value, where, rep, numeric=True):
    if value is None or value == "":
        return
    if not isinstance(value, str):
        return
    allowed = NUMERIC_VARS if numeric else ROLL_VARS
    for var in re.findall(r"\[([^\[\]]+)\]", value):
        if numeric and var != var.upper() and var.upper() in allowed:
            rep.error(f"{where}: переменная [{var}] должна быть заглавной - [{var.upper()}], иначе поле считается как 0")
        elif var.upper() not in allowed:
            rep.error(f"{where}: неизвестная переменная [{var}] (есть {', '.join(sorted(allowed))})")
    if not numeric:
        return
    if re.search(r"\d*[dкDК]\d+", value):
        rep.warn(f"{where}: кости в числовом поле «{value}» считаются как 0")
        return
    expr = re.sub(r"\[[^\[\]]+\]", "1", value).replace("^", "**")
    words = set(re.findall(r"[A-Za-zА-Яа-яЁё_]+", expr))
    if words - FORMULA_FUNCS:
        rep.error(f"{where}: в формуле «{value}» лишние слова: {', '.join(sorted(words - FORMULA_FUNCS))}")
        return
    env = {"floor": lambda x: x // 1, "ceil": lambda x: -(-x // 1), "round": round, "abs": abs,
           "max": max, "min": min, "pow": pow, "sqrt": lambda x: x ** 0.5, "__builtins__": {}}
    try:
        eval(expr, env)  # noqa: S307 - выражение уже ограничено цифрами, операторами и белым списком функций
    except Exception:
        rep.error(f"{where}: формула «{value}» не вычисляется")


def check_text_doc(key, block, rep):
    doc = ((block or {}).get("value") or {}).get("data")
    if not isinstance(doc, dict):
        return

    def visit(node, path):
        t = node.get("type")
        if t not in TEXT_NODE_TYPES:
            rep.error(f"text.{key}{path}: узел «{t}» не поддерживается редактором - весь блок перестанет рисоваться")
        for m in node.get("marks") or []:
            if m.get("type") not in TEXT_MARKS:
                rep.warn(f"text.{key}{path}: разметка «{m.get('type')}» может не поддерживаться")
        if t == "text" and not node.get("text"):
            rep.error(f"text.{key}{path}: пустой text-узел (ProseMirror такое не принимает)")

    walk_nodes(doc, visit, "")


def check_data(envelope, data, rep):
    try:
        import jsonschema
    except ImportError:
        rep.warn("пакет jsonschema не установлен (pip install jsonschema) - проверка схемой пропущена")
        jsonschema = None
    if jsonschema:
        schema = load_json(SCHEMA_PATH)
        validator = jsonschema.Draft7Validator(schema)
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
            path = ".".join(str(p) for p in err.absolute_path) or "(корень)"
            rep.error(f"схема: data.{path}: {err.message[:300]}")

    for k in ("jsonType", "version", "edition", "sheetEdition", "spells", "disabledBlocks"):
        if k not in envelope:
            rep.error(f"в файле нет поля верхнего уровня «{k}»")
    if envelope.get("jsonType") != "character":
        rep.error('jsonType верхнего уровня должен быть "character"')
    if envelope.get("version") != "2":
        rep.error('version должен быть строкой "2"')
    for k in ("edition", "sheetEdition"):
        if envelope.get(k) not in ("2014", "2024"):
            rep.error(f'{k} должен быть "2014" или "2024"')

    info = data.get("info") or {}
    level = level_of(data)
    if not 1 <= level <= 20:
        rep.error(f"уровень {level} вне 1..20")
    expected_prof = 2 + (max(level, 1) - 1) // 4
    if data.get("proficiency") not in (None, expected_prof):
        rep.warn(f"proficiency = {data.get('proficiency')}, а для уровня {level} положено {expected_prof}")
    for a, st in (data.get("stats") or {}).items():
        score = st.get("score") if isinstance(st, dict) else None
        if isinstance(score, (int, float)) and not 1 <= score <= 30:
            rep.error(f"stats.{a}.score = {score} вне 1..30")

    vit = data.get("vitality") or {}
    for k in ("ac", "speed", "initiative"):
        check_formula((vit.get(k) or {}).get("value"), f"vitality.{k}", rep)
    check_formula((vit.get("shield") or {}).get("mod"), "vitality.shield.mod", rep)
    hp_max = (vit.get("hp-max") or {}).get("value")
    hp_cur = (vit.get("hp-current") or {}).get("value")
    if isinstance(hp_max, (int, float)) and isinstance(hp_cur, (int, float)) and hp_cur > hp_max + (vit.get("hp-max-bonus") or {}).get("value", 0):
        rep.warn("hp-current больше максимума хитов")

    si = data.get("spellsInfo") or {}
    for k in ("save", "mod"):
        check_formula((si.get(k) or {}).get("customModifier"), f"spellsInfo.{k}.customModifier", rep)
    for group in ("saves", "skills"):
        for k, v in (data.get(group) or {}).items():
            check_formula(v.get("bonusExpr"), f"{group}.{k}.bonusExpr", rep)
            if isinstance(v.get("customModifier"), str):
                check_formula(v["customModifier"], f"{group}.{k}.customModifier", rep)

    all_ids = {}

    def reg(i, where):
        if i in all_ids:
            rep.error(f"повтор id «{i}»: {all_ids[i]} и {where}")
        all_ids[i] = where

    weapon_ids = set()
    for i, w in enumerate(data.get("weaponsList") or []):
        reg(w.get("id"), f"weaponsList[{i}]")
        weapon_ids.add(w.get("id"))
        check_formula((w.get("dmg") or {}).get("value"), f"weaponsList[{i}].dmg", rep, numeric=False)
        if not (w.get("name") or {}).get("value"):
            rep.error(f"weaponsList[{i}]: нет названия")
    att_ids = set()
    for i, a in enumerate(data.get("attunementsList") or []):
        reg(a.get("id"), f"attunementsList[{i}]")
        att_ids.add(a.get("id"))
    if len(data.get("attunementsList") or []) > 3:
        rep.warn("настроено больше 3 предметов")
    effect_ids = set()
    for i, e in enumerate(data.get("effects") or []):
        reg(e.get("id"), f"effects[{i}]")
        effect_ids.add(e.get("id"))
    for i, b in enumerate(data.get("bonuses") or []):
        where = f"bonuses[{i}]"
        reg(b.get("id"), where)
        target = str(b.get("target", ""))
        m = re.match(r"^weapon\.(.+)\.(attack|damage)$", target)
        if m and m.group(1) not in weapon_ids:
            rep.error(f"{where}: цель {target} ссылается на оружие, которого нет в weaponsList")
        has_value, has_expr = "value" in b, b.get("expr") not in (None, "")
        if b.get("mode") in ("advantage", "disadvantage"):
            pass
        elif has_value == has_expr:
            rep.error(f"{where}: нужно ровно одно из value / expr")
        check_formula(b.get("expr"), f"{where}.expr", rep, numeric=False)
        src = b.get("source") or {}
        if src.get("kind") == "attunement" and src.get("refId") not in att_ids:
            rep.warn(f"{where}: source.kind=attunement, но refId не совпадает с id настройки - бонус не будет "
                     "включаться/выключаться галочкой настройки")
        if src.get("kind") == "effect" and src.get("refId") not in effect_ids:
            rep.error(f"{where}: source.kind=effect, но эффекта с refId «{src.get('refId')}» нет")

    text = data.get("text") or {}
    for k, block in text.items():
        check_text_doc(k, block, rep)
    nodes_by_res = {}
    for k, block in text.items():
        doc = ((block or {}).get("value") or {}).get("data")

        def collect(node, _p, k=k):
            if node.get("type") == "resource":
                nodes_by_res.setdefault((node.get("attrs") or {}).get("id"), []).append(k)

        if isinstance(doc, dict):
            walk_nodes(doc, collect, "")
    resources = data.get("resources") or {}
    for key, r in resources.items():
        where = f"resources.{key}"
        reg(r.get("id"), where)
        if key != r.get("id"):
            rep.error(f"{where}: ключ не совпадает с id «{r.get('id')}»")
        if ("max" in r) == (r.get("maxExpr") not in (None, "")):
            rep.error(f"{where}: нужно ровно одно из max / maxExpr")
        check_formula(r.get("maxExpr"), f"{where}.maxExpr", rep)
        check_formula(r.get("shortRestRegain"), f"{where}.shortRestRegain", rep)
        loc = r.get("location")
        if loc not in text:
            rep.error(f"{where}: location «{loc}» - такого текстового блока нет")
        elif loc not in nodes_by_res.get(r.get("id"), []):
            rep.error(f"{where}: в блоке text.{loc} нет виджета этого ресурса")
        if isinstance(r.get("max"), (int, float)) and r.get("current", 0) > r["max"]:
            rep.warn(f"{where}: current больше max")
    for rid, blocks in nodes_by_res.items():
        if rid not in resources:
            rep.error(f"виджет ресурса «{rid}» в text.{blocks[0]} ссылается на несуществующий ресурс")

    for spell_id, res_id in (si.get("charges") or {}).items():
        if res_id not in resources:
            rep.error(f"spellsInfo.charges.{spell_id}: ресурса «{res_id}» нет")

    for key in ("spells", "spellsPact"):
        for k, v in (data.get(key) or {}).items():
            if isinstance(v, dict) and v.get("filled", 0) > v.get("value", 0):
                rep.warn(f"{key}.{k}: потрачено больше ячеек, чем есть")

    avatar = data.get("avatar") or {}
    if any(str(v).startswith("data:") for v in avatar.values()):
        rep.warn("аватар встроен картинкой (data-URI), а не ссылкой на сервер LSS - формат неофициальный; "
                 "если не отобразится, загрузи картинку кнопкой аватара на листе")

    if data.get("conditions"):
        rep.warn("conditions заполнен - ключи состояний схема не проверяет; для нового персонажа обычно пусто")

    check_spellbook(envelope, data, rep)


def check_spellbook(envelope, data, rep):
    book = envelope.get("spells") or {}
    if not isinstance(book, dict):
        rep.error("spells верхнего уровня должен быть объектом")
        return
    if book.get("mode") not in ("cards", "text"):
        rep.error('spells.mode должен быть "cards" или "text"')
    for k in ("prepared", "book", "granted", "slotless"):
        if not isinstance(book.get(k, []), list):
            rep.error(f"spells.{k} должен быть массивом")
    if book.get("granted"):
        rep.warn("spells.granted пишет только визард LSS - для собранного вручную листа держи его пустым")
    edition = envelope.get("edition")
    if edition not in ("2014", "2024"):
        return
    idx = SpellIndex(edition)
    cid = class_id_of(data.get("info") or {})
    max_slot = 0
    for key in ("spells", "spellsPact"):
        for k, v in (data.get(key) or {}).items():
            if isinstance(v, dict) and v.get("value"):
                max_slot = max(max_slot, int(k.split("-")[1]))
    prepared_ids = set()
    for lst in ("prepared", "book"):
        for ref in book.get(lst) or []:
            sp = idx.by_id.get(ref) or idx.resolve(ref)
            if not sp:
                if re.fullmatch(r"[0-9a-f]{24}", str(ref)):
                    rep.warn(f"spells.{lst}: id {ref} нет в SRD {edition} - либо заклинание из гримуара, "
                             "либо id другой редакции (тогда не найдётся)")
                continue
            if lst == "prepared":
                prepared_ids.add(sp["id"])
            if sp["level"] > max(max_slot, 0) and sp["level"] > 0:
                rep.warn(f"spells.{lst}: «{sp['name']}» {sp['level']} круга, а ячеек выше {max_slot} круга нет")
            if cid and cid in CLASS_CAST_ABILITY and cid not in sp["classes"]:
                rep.warn(f"spells.{lst}: «{sp['name']}» нет в списке класса {cid} "
                         "(нормально, если даёт подкласс, раса, черта или предмет)")
    if cid == "wizard" and not book.get("book"):
        rep.warn("у волшебника пустая книга заклинаний: всё, что в книге, кладётся в spells.book, "
                 "а подготовленное из неё - ещё и в spells.prepared")
    if book.get("book"):
        book_ids = {(idx.by_id.get(r) or idx.resolve(r) or {}).get("id", r) for r in book["book"]}
        for pid in prepared_ids:
            sp = idx.by_id[pid]
            if sp["level"] > 0 and pid not in book_ids:
                rep.warn(f"spells.prepared: «{sp['name']}» подготовлено, но его нет в книге (spells.book)")


# ---------------------------------------------------------------- CLI

def print_report(rep, title):
    for n in rep.notes:
        print(f"  [i] {n}")
    for w in rep.warnings:
        print(f"  [!] {w}")
    for e in rep.errors:
        print(f"  [X] {e}")
    status = "ОШИБКИ" if rep.errors else "OK"
    print(f"{title}: {status} (ошибок {len(rep.errors)}, предупреждений {len(rep.warnings)})")


def write_final(envelope, data, out_path):
    final = dict(envelope)
    final["data"] = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
        f.write("\n")


def cmd_build(args):
    draft = load_json(args.draft)
    rep = Report()
    envelope, data = build(draft, rep, Path(args.draft).resolve().parent)
    try:
        check_data(envelope, data, rep)
    except Exception as e:
        rep.error(f"проверка упала на недособранном черновике ({type(e).__name__}: {e}) - сначала исправь ошибки выше")
    out = Path(args.output) if args.output else Path(args.draft).with_name(
        re.sub(r"(\.draft)?\.json$", "", Path(args.draft).name) + ".lss.json")
    if args.debug:
        dbg = out.with_suffix(".debug.json")
        with open(dbg, "w", encoding="utf-8") as f:
            json.dump({**envelope, "data": data}, f, ensure_ascii=False, indent=2)
        print(f"  [i] развёрнутый вид для отладки: {dbg}")
    if rep.errors:
        print_report(rep, "Сборка")
        print("Файл не записан - исправь черновик и запусти снова.")
        return 1
    write_final(envelope, data, out)
    print_report(rep, "Сборка")
    print(f"Готово: {out}")
    return 0


def cmd_validate(args):
    rep = Report()
    doc = load_json(args.file)
    raw = doc.get("data")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            rep.error(f"data не парсится как JSON: {e}")
            data = None
    elif isinstance(raw, dict):
        rep.error("data должен быть JSON-строкой, а не объектом (нужен JSON.stringify)")
        data = raw
    else:
        rep.error("нет поля data")
        data = None
    if data is not None:
        envelope = {k: v for k, v in doc.items() if k != "data"}
        check_data(envelope, data, rep)
    print_report(rep, f"Проверка {args.file}")
    return 1 if rep.errors else 0


def cmd_spells(args):
    sys.stdout.reconfigure(encoding="utf-8")
    items = load_json(REF_DIR / f"srd-spell-slugs-{args.edition}.json")
    cls = CLASS_ALIASES.get(norm(args.cls), norm(args.cls)) if args.cls else None
    for sp in sorted(items, key=lambda s: (s["level"], s["slug"])):
        if cls and cls not in sp["classes"]:
            continue
        if args.level is not None and sp["level"] != args.level:
            continue
        if args.max_level is not None and sp["level"] > args.max_level:
            continue
        if args.search and norm(args.search) not in norm(sp["name"]) and norm(args.search) not in sp["slug"]:
            continue
        print(f"{sp['level']} | {sp['slug']} | {sp['name']} | {','.join(sp['classes'])}")
    return 0


def cmd_refresh(_args):
    for name, url in REMOTE.items():
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = resp.read()
        json.loads(body)
        (REF_DIR / name).write_bytes(body)
        print(f"обновлено: {name}")
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("draft")
    b.add_argument("-o", "--output")
    b.add_argument("--debug", action="store_true", help="записать рядом развёрнутый вид data объектом")
    v = sub.add_parser("validate")
    v.add_argument("file")
    s = sub.add_parser("spells")
    s.add_argument("--edition", choices=["2014", "2024"], required=True)
    s.add_argument("--class", dest="cls")
    s.add_argument("--level", type=int)
    s.add_argument("--max-level", type=int)
    s.add_argument("--search")
    sub.add_parser("refresh")
    args = p.parse_args()
    handlers = {"build": cmd_build, "validate": cmd_validate, "spells": cmd_spells, "refresh": cmd_refresh}
    sys.exit(handlers[args.cmd](args))


if __name__ == "__main__":
    main()
