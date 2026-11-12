#!/usr/bin/env python3
# 第二轮人工复核：删掉明显不是「这道菜/这个食材」的图，再尝试用 Commons 找回真图
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fetch_images as F

db = F.load_db()
images = F.load_images()
names = {}
for r in db['recipes']:
    names['recipe:' + r['id']] = r['name']
for i in db['ingredients']:
    names['ingredient:' + i['id']] = i['name']

BAD_ING = ['ingredient:msg', 'ingredient:baking_soda', 'ingredient:beef_ribs', 'ingredient:beef_shank',
           'ingredient:beef_tenderloin', 'ingredient:pork_hock', 'ingredient:chicken_whole',
           'ingredient:chrysanthemum_greens', 'ingredient:hairtail', 'ingredient:loach',
           'ingredient:clove', 'ingredient:chicken_carcass', 'ingredient:sea_bass',
           'ingredient:catfish', 'ingredient:cod', 'ingredient:whitebait', 'ingredient:eggplant',
           'ingredient:fava_bean', 'ingredient:cumin']
BAD_RECIPE = ['recipe:braised-beef', 'recipe:potato-chicken-stew', 'recipe:chicken-mushroom-stew',
              'recipe:candied-sweet-potato', 'recipe:wax-gourd-shrimp', 'recipe:pumpkin-cake',
              'recipe:chestnut-chicken', 'recipe:tomato-cauliflower', 'recipe:braised-eggplant',
              'recipe:minced-pork-eggplant', 'recipe:bitter-melon-egg', 'recipe:lotus-stir-fry',
              'recipe:garlic-broccoli', 'recipe:oyster-lettuce', 'recipe:hot-sour-potato',
              'recipe:old-vinegar-peanut', 'recipe:fish-tofu-soup', 'recipe:vinegar-cabbage',
              'recipe:mushroom-bokchoy', 'recipe:garlic-spinach', 'recipe:cucumber-egg',
              'recipe:cold-cucumber']

def drop(key):
    v = images.pop(key, None)
    if v:
        p = os.path.join(F.ROOT, v['file'])
        if os.path.exists(p):
            os.remove(p)
        return True
    return False

for k in BAD_ING + BAD_RECIPE:
    drop(k)
print('dropped ->', len(images))

# 酱油三兄弟：改查 en.wikipedia Soy sauce（zh 酱油 的 pageimage 是张建筑照片）
soy = F.batch_page_images(['Soy sauce'], F.EN)
h = soy.get(F.norm_title('Soy sauce'))
if h:
    metas = F.batch_file_meta([h['file']], F.COMMONS)
    m = metas.get(F.norm_title(h['file']))
    if m and F.license_ok(m):
        for oid in ('light_soy', 'dark_soy', 'steamed_fish_soy'):
            key = 'ingredient:' + oid
            fn = 'ing-' + oid + '.jpg'
            path = os.path.join(F.IMG_DIR, fn)
            if os.path.exists(path):
                os.remove(path)
            try:
                data = F.download(h['thumb'])
                px, size = F.save_image(data, path)
            except Exception as e:
                print('dl fail', key, e); continue
            if not px:
                continue
            images[key] = {'file': 'images/' + fn, 'source': 'en.wikipedia.org', 'title': h['title'],
                           'page_url': m.get('descurl') or '', 'license': m['license'],
                           'author': m['author'], 'px': px, 'bytes': size}
            print('soy fixed', key, h['title'], m['license'])

# 对删掉的菜再试一次 Commons 搜索（中文名 + 英文名）
for key in BAD_RECIPE:
    if key in images:
        continue
    rid = key.split(':')[1]
    zh = names.get(key, '')
    cands = [zh] + ([F.EN_RECIPE.get(rid)] if F.EN_RECIPE.get(rid) else [])
    got = None
    for term in cands:
        if not term:
            continue
        res = F.commons_search(term, 3)
        for r in res or []:
            if F.title_score(term, r['title'], zh) >= 2:
                got = r
                break
        if got:
            break
    if not got:
        continue
    try:
        data = F.download(got['thumb'])
        fn = 'recipe-' + rid + '.jpg'
        px, size = F.save_image(data, os.path.join(F.IMG_DIR, fn))
    except Exception as e:
        print('dl fail', key, e); continue
    if not px:
        continue
    images[key] = {'file': 'images/' + fn, 'source': 'commons.wikimedia.org', 'title': got['title'],
                   'page_url': got.get('descurl') or '', 'license': got['license'],
                   'author': got['author'], 'px': px, 'bytes': size}
    print('commons refill', key, got['title'], got['license'])

total = F.shrink_if_needed(images)
nmiss = F.write_outputs(db, images)
print('total %.1f MB entries %d missing %d' % (total / 1048576.0, len(images), nmiss))
