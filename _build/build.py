# -*- coding: utf-8 -*-
import json, io, os
from ingredients import INGREDIENTS
import batch1, batch2, batch3

R = batch1.RECIPES + batch2.RECIPES + batch3.RECIPES

# 首页优先展示的招牌菜（其余保持原顺序）
PRIORITY = [
    "tomato-egg", "braised-pork", "kungpao-chicken", "mapo-tofu", "cola-chicken-wings",
    "sweet-sour-ribs", "tomato-egg-noodle", "smashed-cucumber", "steamed-egg-custard",
    "garlic-broccoli", "sour-potato-shred", "yuxiang-pork", "scallion-oil-noodle",
    "claypot-rice", "white-cut-chicken", "beer-duck",
]
by_id = {r["id"]: r for r in R}
missing = [p for p in PRIORITY if p not in by_id]
if missing:
    print("priority missing:", missing)
ordered = [by_id[p] for p in PRIORITY if p in by_id] + [r for r in R if r["id"] not in PRIORITY]

ingredients = []
for (iid, name, alias, cat, unit, emoji) in INGREDIENTS:
    ingredients.append({"id": iid, "name": name, "alias": alias, "category": cat, "unit": unit, "emoji": emoji})

categories = ["蔬菜", "肉禽", "水产", "蛋奶", "豆制品", "主食", "调料", "干货/菌菇"]
tags = ["快手", "素菜", "汤", "下饭", "宴客", "早餐"]

db = {"ingredients": ingredients, "recipes": ordered, "categories": categories, "tags": tags}

out = io.StringIO()
out.write("/* 菜谱数据 —— 由 build.py 自动生成，请勿手改。\n")
out.write("   食材 %d 种 / 菜谱 %d 道\n" % (len(ingredients), len(ordered)))
out.write("   纯静态内联：双击 index.html 即可离线使用，无任何网络请求。 */\n")
out.write("window.RECIPE_DB = ")
out.write(json.dumps(db, ensure_ascii=False, indent=0, separators=(",", ":")))
out.write(";\n")

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data.js")
open(path, "w", encoding="utf-8").write(out.getvalue())
print("wrote", os.path.abspath(path), os.path.getsize(path), "bytes")
print("ingredients", len(ingredients), "recipes", len(ordered))
