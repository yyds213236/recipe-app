# -*- coding: utf-8 -*-
import re, sys, importlib
from ingredients import INGREDIENTS
import batch1, batch2, batch3

NAMES = {i[0] for i in INGREDIENTS}
RECIPES = batch1.RECIPES + batch2.RECIPES + batch3.RECIPES

def cn_len(s):
    return len(s)

problems = []
ids = {}
for rc in RECIPES:
    if rc["id"] in ids:
        problems.append(("dup-id", rc["id"]))
    ids[rc["id"]] = 1
    for ing in rc["ingredients"]:
        if ing["id"] not in NAMES:
            problems.append(("bad-ing", rc["id"], ing["id"]))
    if not (1 <= len(rc["ingredients"])):
        problems.append(("no-ing", rc["id"]))
    if len(rc["steps"]) < 4 or len(rc["steps"]) > 8:
        problems.append(("step-count", rc["id"], len(rc["steps"])))
    for s in rc["steps"]:
        n = cn_len(s)
        if n < 15 or n > 60:
            problems.append(("step-len", rc["id"], n, s))

# duplicated ingredient id inside a recipe
for rc in RECIPES:
    seen = set()
    for ing in rc["ingredients"]:
        if ing["id"] in seen:
            problems.append(("dup-ing-in-recipe", rc["id"], ing["id"]))
        seen.add(ing["id"])

print("recipes:", len(RECIPES), "ingredients:", len(NAMES))
from collections import Counter
print("by cuisine:", Counter(r["cuisine"] for r in RECIPES))
print("problems:", len(problems))
for p in problems[:200]:
    print(p)
