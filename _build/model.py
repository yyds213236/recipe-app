# -*- coding: utf-8 -*-
def r(rid, name, emoji, cuisine, tags, time, diff, ing, steps, servings=2):
    return dict(id=rid, name=name, emoji=emoji, cuisine=cuisine, tags=tags,
                time=time, difficulty=diff, servings=servings,
                ingredients=ing, steps=steps)

def I(iid, amount, unit, optional=False):
    return dict(id=iid, amount=amount, unit=unit, optional=optional)

RECIPES = []
