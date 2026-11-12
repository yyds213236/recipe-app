#!/usr/bin/env python3
# 人工复核后的定点修补：把明显配错的图换成更准的词条，换不到就删掉回退 emoji
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fetch_images as F

ROOT = F.ROOT
db = F.load_db()
images = F.load_images()

DROP = ['recipe:steamed-perch', 'recipe:three-delicacy-soup', 'recipe:tiger-pepper',
        'recipe:three-cup-chicken', 'recipe:millet-pumpkin-congee', 'recipe:corn-ribs-soup']

CASES = {
    'recipe:three-cup-chicken': [('zh', '三杯雞'), ('zh', '三杯鸡')],
    'recipe:steamed-perch': [('zh', '清蒸鱸魚'), ('zh', '鱸魚')],
    'recipe:tiger-pepper': [('zh', '虎皮青椒')],
    'recipe:three-delicacy-soup': [('zh', '三鮮湯')],
    'recipe:millet-pumpkin-congee': [('zh', '小米粥')],
    'recipe:corn-ribs-soup': [('zh', '玉米排骨湯')],
}

for k in DROP:
    v = images.pop(k, None)
    if v and os.path.exists(os.path.join(ROOT, v['file'])):
        os.remove(os.path.join(ROOT, v['file']))

for key, cands in CASES.items():
    hit = None
    for base_name, title in cands:
        base = {'zh': F.ZH, 'en': F.EN}[base_name]
        got = F.batch_page_images([title], base)
        if not got:
            continue
        h = got.get(F.norm_title(title))
        if not h:
            continue
        hit = (base_name, h)
        break
    if not hit:
        print('no hit', key)
        continue
    base_name, h = hit
    metas = F.batch_file_meta([h['file']], F.COMMONS)
    m = metas.get(F.norm_title(h['file']))
    if not m or not F.license_ok(m):
        print('license fail', key, h['file'], m and m['license'])
        continue
    kind, oid = key.split(':')
    fname = ('recipe-' if kind == 'recipe' else 'ing-') + oid + '.jpg'
    path = os.path.join(F.IMG_DIR, fname)
    try:
        data = F.download(h['thumb'])
        px, size = F.save_image(data, path)
    except Exception as e:
        print('dl fail', key, e)
        continue
    if not px:
        print('save fail', key)
        continue
    images[key] = {
        'file': 'images/' + fname, 'source': ('zh.wikipedia.org' if base_name == 'zh' else 'en.wikipedia.org'),
        'title': h['title'],
        'page_url': m.get('descurl') or '',
        'license': m['license'], 'author': m['author'], 'px': px, 'bytes': size,
    }
    print('fixed', key, '->', h['title'], m['license'])

total = F.shrink_if_needed(images)
nmiss = F.write_outputs(db, images)
print('total %.1f MB, entries %d, missing %d' % (total / 1048576.0, len(images), nmiss))
