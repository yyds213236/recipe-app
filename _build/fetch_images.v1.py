#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_images.py —— 给「小锅菜谱」抓真实配图。

数据源只用允许自由使用的图源，按优先级：
  1. 中文维基百科 pageimages（词条=菜名 / 食材名）
  2. 英文维基百科 pageimages（菜名→英文名映射表）
  3. 维基共享资源 Commons 搜索（gsrnamespace=6，只搜文件）
  4. 都没有 → 不写条目，前端继续用 emoji 占位

每张图都从 imageinfo.extmetadata 读 LicenseShortName / Artist / Credit，
CC-BY(-SA)、CC0、PD 才收；遇到 fair-use / 非自由许可直接放弃，换下一档。

用法：
  python3 fetch_images.py                 # 全量（断点续跑：已存在且文件在的条目跳过）
  python3 fetch_images.py --only recipe   # 只跑菜谱
  python3 fetch_images.py --only ingredient
  python3 fetch_images.py --limit 20      # 调试
  python3 fetch_images.py --rebuild       # 只重建 images-data.js / missing-images.txt

依赖：Python 3 标准库（urllib/json/re/subprocess）+ macOS 自带 sips。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(ROOT, 'images')
OUT_JSON = os.path.join(ROOT, 'images.json')
OUT_JS = os.path.join(ROOT, 'images-data.js')
MISSING_TXT = os.path.join(ROOT, 'missing-images.txt')

ZH = 'https://zh.wikipedia.org/w/api.php'
EN = 'https://en.wikipedia.org/w/api.php'
COMMONS = 'https://commons.wikimedia.org/w/api.php'

UA = 'RecipePhotosFetcher/1.0 (offline recipe demo; personal local use)'
MIN_GAP = 0.9          # 全局限速：两次请求之间至少 0.9s（维基对共享出口 IP 限流）
MAX_BYTES = 120 * 1024 # 单张 120KB
THUMB_W = 600

# ---------------------------------------------------------------- 菜名 → 英文维基词条
# 只写“有机会命中 en.wikipedia”的名字；命中不了会自动落到 Commons 搜索。
EN_RECIPE = {
    'tomato-egg': ['Stir-fried tomato and scrambled eggs'],
    'braised-pork': ['Red braised pork belly', 'Hong shao rou'],
    'kungpao-chicken': ['Kung Pao chicken'],
    'mapo-tofu': ['Mapo tofu'],
    'cola-chicken-wings': ['Coca-Cola chicken wings'],
    'sweet-sour-ribs': ['Sweet and sour spare ribs', 'Sweet and sour pork'],
    'tomato-egg-noodle': ['Stir-fried tomato and scrambled eggs'],
    'smashed-cucumber': ['Pai huang gua', 'Smashed cucumber salad'],
    'steamed-egg-custard': ['Steamed egg', 'Chinese steamed egg'],
    'garlic-broccoli': ['Broccoli'],
    'sour-potato-shred': ['Shredded potato', 'Potato'],
    'yuxiang-pork': ['Yuxiang shredded pork'],
    'scallion-oil-noodle': ['Scallion oil noodles'],
    'claypot-rice': ['Claypot rice', 'Bao zai fan'],
    'white-cut-chicken': ['White cut chicken'],
    'beer-duck': ['Beer duck', 'Duck as food'],
    'twice-cooked-pork': ['Twice cooked pork'],
    'hand-torn-cabbage': ['Cabbage'],
    'dry-fried-green-beans': ['Dry-fried green beans', 'Green bean'],
    'disanxian': ['Di san xian'],
    'braised-eggplant': ['Braised eggplant', 'Eggplant'],
    'vinegar-cabbage': ['Napa cabbage'],
    'chive-egg': ['Scrambled eggs'],
    'onion-egg': ['Scrambled eggs'],
    'bitter-melon-egg': ['Bitter melon'],
    'celery-lily': ['Celery'],
    'lotus-stirfry': ['Lotus root'],
    'oyster-lettuce': ['Lettuce'],
    'spinach-century-egg': ['Spinach'],
    'mushroom-bokchoy': ['Bok choy'],
    'tomato-cauliflower': ['Cauliflower'],
    'pepper-pork': ['Twice cooked pork'],
    'farmhouse-pork': ['Twice cooked pork'],
    'celery-tofu': ['Tofu'],
    'chive-sprout': ['Mung bean sprout', 'Bean sprout'],
    'ants-tree': ['Ants climbing a tree'],
    'minced-pork-eggplant': ['Eggplant'],
    'langya-potato': ['Potato'],
    'yam-wood-ear': ['Chinese yam', 'Wood ear'],
    'stirfry-lettuce-stem': ['Celtuce'],
    'garlic-water-spinach': ['Water spinach'],
    'loofah-egg': ['Luffa'],
    'winter-melon-shrimp': ['Winter melon'],
    'shrimp-scrambled-egg': ['Scrambled eggs'],
    'jingjiang-pork': ['Sweet bean sauce'],
    'mushu-pork': ['Moo shu pork'],
    'sweet-sour-pork': ['Sweet and sour pork'],
    'three-cup-chicken': ['Three cup chicken'],
    'spicy-chicken': ['Laziji', 'Chongqing chicken'],
    'cumin-lamb': ['Cumin lamb'],
    'scallion-lamb': ['Lamb and scallion stir-fry', 'Lamb'],
    'black-pepper-beef': ['Black pepper beef', 'Beef'],
    'garlic-sprout-sausage': ['Chinese sausage'],
    'tiger-pepper': ['Green pepper'],
    'dry-pot-cauliflower': ['Cauliflower'],
    'salt-pepper-shrimp': ['Salt and pepper shrimp', 'Shrimp'],
    'garlic-ribs': ['Spare ribs'],
    'tomato-egg-soup': ['Tomato and egg soup', 'Egg drop soup'],
    'laver-egg-soup': ['Egg drop soup'],
    'winter-melon-ribs-soup': ['Winter melon soup', 'Pork ribs'],
    'corn-ribs-soup': ['Corn soup'],
    'lotus-ribs-soup': ['Lotus root soup'],
    'yam-chicken-soup': ['Chicken soup'],
    'radish-beef-soup': ['Beef soup', 'Beef noodle soup'],
    'crucian-tofu-soup': ['Tofu soup', 'Crucian carp'],
    'hot-sour-soup': ['Hot and sour soup'],
    'dough-drop-soup': ['Tomato and egg soup'],
    'winter-melon-meatball-soup': ['Winter melon soup', 'Meatball'],
    'loofah-egg-soup': ['Egg drop soup'],
    'mushroom-soup': ['Mushroom soup'],
    'kelp-tofu-soup': ['Tofu soup', 'Kelp'],
    'spinach-liver-soup': ['Spinach', 'Pork liver'],
    'borscht': ['Borscht'],
    'oxtail-tomato-soup': ['Oxtail soup'],
    'three-delicacy-soup': ['Soup'],
    'hulatang': ['Hu la tang', 'Hulatang'],
    'cabbage-tofu-soup': ['Tofu soup'],
    'steamed-perch': ['Steamed fish'],
    'steamed-ribs-rice-powder': ['Spare ribs'],
    'garlic-vermicelli-loofah': ['Luffa'],
    'meicai-meat-pie': ['Meigan cai', 'Steamed pork patty'],
    'steamed-chicken-mushroom': ['Steamed chicken'],
    'chopped-chili-tofu': ['Tofu'],
    'salted-fish-meat-pie': ['Steamed pork with salted fish'],
    'pearl-meatball': ['Meatball'],
    'garlic-steamed-eggplant': ['Steamed eggplant'],
    'steamed-crab': ['Chinese mitten crab'],
    'tomato-beef-brisket': ['Beef brisket'],
    'potato-chicken-stew': ['Chicken stew'],
    'soybean-pork-trotter': ['Pig trotter'],
    'peanut-pork-trotter': ['Pig trotter'],
    'chestnut-chicken': ['Chestnut chicken', 'Chestnut'],
    'braised-spare-ribs': ['Spare ribs'],
    'radish-braised-pork': ['Braised pork'],
    'dry-pot-tea-tree-mushroom': ['Agrocybe aegerita'],
    'chicken-mushroom-stew': ['Chicken stew'],
    'pork-vermicelli-stew': ['Cellophane noodles'],
    'pickled-cabbage-pork': ['Suan cai'],
    'curry-beef': ['Beef curry'],
    'braised-beef-shank': ['Beef shank'],
    'lion-head': ["Lion's head"],
    'braised-chicken-feet': ['Chicken feet'],
    'boiled-beef-sichuan': ['Sichuan boiled beef'],
    'sour-soup-beef-roll': ['Beef'],
    'dongpo-pork': ['Dongpo pork'],
    'potato-beef-stew': ['Beef stew'],
    'cold-wood-ear': ['Wood ear'],
    'cold-kelp': ['Kelp'],
    'cold-yuba': ['Yuba'],
    'cold-chicken-shreds': ['Bang bang chicken'],
    'century-egg-tofu': ['Century egg'],
    'old-vinegar-peanut': ['Peanut'],
    'sesame-spinach': ['Spinach'],
    'cold-three-shreds': ['Shredded'],
    'cold-enoki': ['Enoki mushroom'],
    'cold-okra': ['Okra'],
    'zhajiang-noodle': ['Zhajiangmian'],
    'lanzhou-beef-noodle': ['Lanzhou beef noodles'],
    'dandan-noodle': ['Dandan noodles'],
    'beef-chow-fun': ['Beef chow fun'],
    'egg-fried-rice': ['Fried rice'],
    'yangzhou-fried-rice': ['Yangzhou fried rice'],
    'braised-pork-rice': ['Lu rou fan'],
    'curry-chicken-rice': ['Japanese curry'],
    'tomato-beef-noodle': ['Beef noodle soup'],
    'pork-cabbage-dumpling': ['Jiaozi'],
    'chive-pocket': ['Chinese chives'],
    'three-delicacy-wonton': ['Wonton'],
    'pan-fried-bun': ['Shengjian mantou'],
    'scallion-pancake': ['Cong you bing'],
    'sour-hot-noodle': ['Suan la fen'],
    'chongqing-noodle': ['Chongqing noodles'],
    'oil-splashed-noodle': ['You po mian', 'Biangbiang noodles'],
    'xinjiang-pilaf': ['Polo (dish)', 'Pilaf'],
    'sausage-sticky-rice': ['Lo mai fan', 'Glutinous rice'],
    'century-egg-congee': ['Congee'],
    'millet-pumpkin-congee': ['Millet', 'Congee'],
    'tomato-egg-pancake': ['Pancake'],
    'tea-egg': ['Tea egg'],
    'tofu-pudding': ['Douhua'],
    'soy-milk': ['Soy milk'],
    'squirrel-fish': ['Squirrel fish'],
    'chopped-chili-fish-head': ['Fish head'],
    'braised-fish-chunks': ['Braised fish'],
    'saliva-chicken': ['Saliva chicken', 'Kou shui ji'],
    'maoxuewang': ['Mao xue wang'],
    'couple-lung-slices': ['Fuqi feipian'],
    'tremella-soup': ['Snow fungus'],
    'mung-bean-soup': ['Mung bean soup'],
    'double-skin-milk': ['Double skin milk'],
    'candied-sweet-potato': ['Candied sweet potato'],
    'pumpkin-cake': ['Pumpkin'],
    'lvdagun': ['Lü da gun', 'Lvdagun'],
    'osmanthus-rice-ball': ['Tangyuan'],
}

# ---------------------------------------------------------------- 食材 → 中文维基词条
# 大多数食材名本身就是词条；这里只放“叫法对不上词条”的替换。
ZH_ING = {
    'bokchoy': '小白菜', 'garlic_sprout': '蒜', 'hot_pepper': '辣椒', 'red_pepper': '辣椒',
    'bell_pepper': '甜椒', 'cabbage': '卷心菜', 'cauliflower': '花椰菜',
    'rape': '菜心', 'pea_shoot': '豌豆苗', 'zucchini': '西葫芦',
    'pork_loin': '里脊', 'pork_mince': '猪肉', 'pig': '猪肉', 'pork_ribs': '排骨',
    'pork_hock': '猪脚', 'pork_kidney': '猪腰子', 'pork_intestine': '猪大肠',
    'pork_shoulder': '梅花肉', 'lean_pork': '猪肉', 'beef_mince': '牛肉',
    'beef_ribs': '牛小排', 'beef_roll': '肥牛', 'lamb_leg': '羊肉', 'lamb_roll': '羊肉',
    'chicken_whole': '鸡', 'chicken_mince': '鸡肉', 'chicken_bones': '鸡',
    'duck': '鸭', 'rabbit': '兔肉', 'grass_carp': '草鱼', 'bighead_carp': '鳙鱼',
    'yellow_croaker': '黄花鱼', 'mandarin_fish': '鳜鱼', 'prawn': '基围虾',
    'crab': '大闸蟹', 'mussel': '贻贝', 'scallop': '扇贝', 'clam': '花蛤',
    'razor_clam': '蛏子', 'oyster': '生蚝', 'abalone': '鲍鱼', 'jellyfish': '海蜇',
    'shrimp': '虾仁', 'crab_stick': '蟹棒', 'cheese': '奶酪', 'cream': '淡奶油',
    'condensed_milk': '炼乳', 'coconut_milk': '椰奶', 'egg_white': '蛋白',
    'tofu': '豆腐', 'silken_tofu': '豆腐', 'soybean': '大豆', 'red_bean': '红小豆',
    'kidney_bean': '芸豆', 'rice': '稻', 'millet': '粟', 'flour': '面粉',
    'high_gluten_flour': '面粉', 'low_gluten_flour': '面粉', 'wheat_noodle': '面条',
    'fresh_noodle': '面条', 'rice_noodle_roll': '河粉', 'wonton_wrapper': '馄饨',
    'salt': '食盐', 'soy_sauce': '酱油', 'dark_soy': '酱油', 'vinegar': '醋',
    'black_vinegar': '醋', 'white_vinegar': '醋', 'sichuan_pepper_oil': '花椒',
    'seasoned_soy': '酱油', 'white_pepper': '胡椒', 'star_anise': '八角',
    'fennel_seed': '茴香', 'bay_leaf': '月桂叶', 'chili_powder': '辣椒粉',
    'curry_powder': '咖喱', 'curry_cube': '咖喱', 'starch': '淀粉',
    'potato_starch': '淀粉', 'baking_soda': '碳酸氢钠', 'chicken_bouillon': '鸡精',
    'msg': '味精', 'sesame': '芝麻', 'garlic_chili_sauce': '辣椒酱',
    'char_siu_sauce': '叉烧', 'sweet_osmanthus': '桂花', 'dried_chili': '辣椒',
    'fermented_chili': '剁椒', 'pickled_pepper': '泡椒', 'douchi': '豆豉',
    'hoisin_sauce': '海鲜酱', 'yellow_bean_sauce': '黄豆酱', 'bean_paste': '豆瓣酱',
    'soup_stock': '高汤', 'bamboo_shoot': '春笋', 'water_chestnut': '荸荠',
    'asparagus_lettuce': '莴笋', 'chrysanthemum': '茼蒿', 'toon': '香椿',
    'mustard_green': '芥菜', 'amaranth': '苋菜', 'yam': '山药',
    'black_bean': '黑豆', 'mung_bean': '绿豆', 'gluinous_rice': '糯米',
    'glutinous_rice': '糯米', 'black_rice': '黑米', 'oats': '燕麦',
    'rice_noodle': '米粉', 'vermicelli': '粉丝', 'sweet_potato_noodle': '红薯粉',
    'instant_noodle': '方便面', 'dumpling_wrapper': '饺子皮', 'cornmeal': '玉米面',
    'buckwheat_noodle': '荞麦面', 'sago': '西米', 'youtiao': '油条',
    'hand_pancake': '手抓饼', 'rice_roll': '肠粉', 'guoba': '锅巴',
    'dried_mushroom': '香菇', 'white_fungus': '银耳', 'oyster_mushroom': '平菇',
    'king_oyster': '杏鲍菇', 'button_mushroom': '口蘑', 'straw_mushroom': '草菇',
    'tea_tree_mushroom': '茶树菇', 'bamboo_fungus': '竹荪', 'morel': '羊肚菌',
    'porcini': '牛肝菌', 'cordyceps_flower': '蛹虫草', 'matsutake': '松茸',
    'laver': '紫菜', 'nori': '海苔', 'dried_squid': '鱿鱼', 'dried_whitebait': '银鱼',
    'preserved_veg': '梅干菜', 'pickled_cabbage': '酸菜', 'zhacai': '榨菜',
    'dried_bamboo': '笋干', 'chestnut': '板栗', 'red_date': '枣', 'goji': '枸杞',
    'dried_longan': '龙眼', 'lotus_seed': '莲子', 'dried_lily': '百合',
    'job_tears': '薏苡', 'daylily': '黄花菜', 'fish_maw': '鱼肚',
    'cream_cheese': '奶油奶酪', 'mozzarella': '马苏里拉奶酪', 'salted_yolk': '咸蛋黄',
    'evaporated_milk': '淡奶', 'yacai': '芽菜', 'chickpea': '鹰嘴豆',
    'broad_bean': '蚕豆', 'pea': '豌豆', 'fermented_rice': '酒酿',
    'pickled_pepper': '泡椒', 'preserved_veg': '梅干菜',
    'salted_fish': '咸鱼', 'dried_shrimp': '虾皮', 'dried_scallop': '干贝',
    'century_egg': '皮蛋', 'salted_egg': '咸鸭蛋', 'quail_egg': '鹌鹑蛋',
}

# 食材的英文兜底（zh 没命中时查 en）
EN_ING = {
    'tomato': ['Tomato'], 'potato': ['Potato'], 'egg': ['Chicken egg', 'Egg as food'],
    'pork_belly': ['Pork belly'], 'scallion': ['Scallion'], 'ginger': ['Ginger'],
    'garlic': ['Garlic'], 'onion': ['Onion'], 'soy_sauce': ['Soy sauce'],
    'vinegar': ['Vinegar'], 'chili_oil': ['Chili oil'], 'peppercorn': ['Sichuan pepper'],
    'oyster_sauce': ['Oyster sauce'], 'rice_wine': ['Shaoxing wine', 'Rice wine'],
    'sesame_oil': ['Sesame oil'], 'starch': ['Corn starch'], 'tofu': ['Tofu'],
    'bokchoy': ['Bok choy'], 'napa': ['Napa cabbage'], 'water_spinach': ['Water spinach'],
    'lotus_root': ['Lotus root'], 'winter_melon': ['Winter melon'], 'loofah': ['Luffa'],
    'bitter_melon': ['Bitter melon'], 'okra': ['Okra'], 'yam': ['Chinese yam'],
    'sweet_potato': ['Sweet potato'], 'taro': ['Taro'], 'corn': ['Maize'],
    'shiitake': ['Shiitake'], 'wood_ear': ['Wood ear'], 'enoki': ['Enokitake'],
    'kelp': ['Kelp'], 'laver': ['Nori'], 'peanut': ['Peanut'], 'walnut': ['Walnut'],
    'cashew': ['Cashew'], 'chestnut': ['Chestnut'], 'red_date': ['Jujube'],
    'goji': ['Goji'], 'lotus_seed': ['Lotus seed'], 'honey': ['Honey'],
    'rock_sugar': ['Rock candy'], 'beer': ['Beer'], 'cola': ['Cola'],
    'lemon': ['Lemon'], 'milk': ['Milk'], 'butter': ['Butter'], 'cheese': ['Cheese'],
    'yogurt': ['Yogurt'], 'shrimp': ['Shrimp'], 'prawn': ['Prawn'],
    'crab': ['Chinese mitten crab'], 'crayfish': ['Procambarus clarkii'],
    'squid': ['Squid'], 'scallop': ['Scallop'], 'oyster': ['Oyster'],
    'salmon': ['Salmon'], 'cod': ['Cod'], 'perch': ['Perch'],
    'chicken_leg': ['Chicken as food'], 'chicken_wing': ['Chicken wings'],
    'chicken_feet': ['Chicken feet'], 'duck': ['Duck as food'],
    'beef_brisket': ['Beef brisket'], 'pork_ribs': ['Spare ribs'],
    'pork_hock': ['Pig trotter'], 'bacon': ['Bacon'], 'sausage': ['Sausage'],
    'ham': ['Ham'], 'flour': ['Wheat flour'], 'rice': ['Rice'],
    'glutinous_rice': ['Glutinous rice'], 'millet': ['Foxtail millet'],
    'wheat_noodle': ['Noodle'], 'vermicelli': ['Cellophane noodles'],
    'bread': ['Bread'], 'steamed_bun': ['Mantou'], 'rice_cake': ['Nian gao'],
    'tangyuan': ['Tangyuan'], 'youtiao': ['Youtiao'],
    'century_egg': ['Century egg'], 'salted_egg': ['Salted duck egg'],
    'quail_egg': ['Quail eggs'], 'sea_cucumber': ['Sea cucumber'],
    'abalone': ['Abalone'], 'jellyfish': ['Jellyfish as food'],
}

RE_LICENSE_OK = re.compile(r'(cc[ -]?by|cc0|public domain|pd-|gfdl|free art)', re.I)
RE_LICENSE_BAD = re.compile(r'(fair use|non-free|non free|copyright)', re.I)

# ---------------------------------------------------------------- 基础设施
_lock = threading.Lock()
_last_req = [0.0]
_stats_lock = threading.Lock()
_stats = {'req': 0}


def throttle():
    """全局 0.3s 请求间隔（线程安全）。"""
    with _lock:
        gap = time.time() - _last_req[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _last_req[0] = time.time()


def api(base, params, timeout=20):
    params = dict(params)
    params.setdefault('format', 'json')
    params.setdefault('formatversion', '2')
    url = base + '?' + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(6):
        throttle()
        with _stats_lock:
            _stats['req'] += 1
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                try:
                    wait = float(e.headers.get('Retry-After') or 0)
                except Exception:  # noqa: BLE001
                    wait = 0.0
                time.sleep(max(wait, 3.0) + 0.5 * (attempt + 1))
                continue
            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
    raise last_err


def strip_html(s):
    s = re.sub(r'<[^>]+>', ' ', str(s or ''))
    s = s.replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def meta_of(md):
    def g(k):
        v = md.get(k) or {}
        return strip_html(v.get('value', ''))

    lic = g('LicenseShortName') or g('License')
    author = g('Artist') or g('Credit') or 'Unknown'
    if len(author) > 140:
        author = author[:140].rstrip() + '…'
    copyrighted = g('Copyrighted')
    usage = g('UsageTerms')
    return {
        'license': lic or 'Unknown',
        'author': author,
        'license_url': g('LicenseUrl'),
        'copyrighted': copyrighted,
        'usage': usage,
    }


def license_ok(meta):
    lic = (meta.get('license') or '') + ' ' + (meta.get('usage') or '')
    if RE_LICENSE_BAD.search(lic) and not RE_LICENSE_OK.search(lic):
        return False
    if RE_LICENSE_OK.search(lic):
        return True
    # 没有明确许可信息的图（多为 PD-old）也接受，但要求不是标志性 copyrighted
    return meta.get('copyrighted') != 'True'


def page_image(base, title):
    """返回 {'title','thumb','file'} 或 None。"""
    data = api(base, {
        'action': 'query', 'titles': title, 'prop': 'pageimages',
        'pithumbsize': THUMB_W, 'redirects': '1',
    })
    for p in (data.get('query', {}).get('pages') or []):
        if p.get('missing') or p.get('invalid'):
            continue
        th = p.get('thumbnail') or {}
        src = (th.get('source') or '').split('?')[0]
        if not src or src.lower().endswith('.svg'):
            continue
        return {'title': p.get('title') or title, 'thumb': src, 'file': p.get('pageimage') or ''}
    return None


def file_meta(fname):
    """在 Commons / zh / en 里找 File:<fname> 的许可信息。"""
    if not fname:
        return None
    for base in (COMMONS, ZH, EN):
        try:
            data = api(base, {
                'action': 'query', 'titles': 'File:' + fname, 'prop': 'imageinfo',
                'iiprop': 'url|extmetadata|size',
                'iiextmetadatafilter': 'LicenseShortName|License|Artist|Credit|UsageTerms|Copyrighted|LicenseUrl',
            })
        except Exception:  # noqa: BLE001
            continue
        for p in (data.get('query', {}).get('pages') or []):
            if p.get('missing') or p.get('invalid'):
                continue
            ii = (p.get('imageinfo') or [{}])[0]
            if not ii:
                continue
            m = meta_of(ii.get('extmetadata') or {})
            m['descurl'] = ii.get('descriptionurl') or ''
            m['width'] = ii.get('width') or 0
            m['height'] = ii.get('height') or 0
            return m
    return None


def commons_search(term, limit=5):
    """Commons 文件搜索，返回带许可信息的候选列表。"""
    try:
        data = api(COMMONS, {
            'action': 'query', 'generator': 'search', 'gsrsearch': term,
            'gsrlimit': str(limit), 'gsrnamespace': '6',
            'prop': 'imageinfo', 'iiprop': 'url|extmetadata|size|mime',
            'iiurlwidth': str(THUMB_W),
        })
    except Exception:  # noqa: BLE001
        return []
    out = []
    pages = (data.get('query', {}).get('pages') or [])
    pages.sort(key=lambda p: p.get('index', 99))
    for p in pages:
        ii = (p.get('imageinfo') or [{}])[0]
        if not ii:
            continue
        mime = ii.get('mime', '')
        if mime not in ('image/jpeg', 'image/png'):
            continue
        if (ii.get('width') or 0) < 480:
            continue
        thumb = (ii.get('thumburl') or ii.get('url') or '').split('?')[0]
        if not thumb:
            continue
        m = meta_of(ii.get('extmetadata') or {})
        m.update({
            'title': re.sub(r'\.(jpg|jpeg|png)$', '', p.get('title', '').replace('File:', ''), flags=re.I),
            'thumb': thumb,
            'file': p.get('title', '').replace('File:', ''),
            'page_url': ii.get('descriptionurl') or '',
        })
        out.append(m)
    return out


def download(url):
    throttle()
    with _stats_lock:
        _stats['req'] += 1
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Accept': 'image/jpeg,image/png,image/*;q=0.8',
        'Referer': 'https://commons.wikimedia.org/',
    })
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def _sips(src, dst, maxdim, quality):
    cmd = ['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', str(quality),
           '-Z', str(maxdim), src, '--out', dst]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError('sips: ' + p.stderr.decode('utf-8', 'replace')[:200])


def save_jpeg(raw, out_path):
    """写文件并按需压到 ≤120KB；超了先降质量再降到 400px。"""
    ext = '.png' if raw[:8] == b'\x89PNG\r\n\x1a\n' else '.jpg'
    fd, tmp = tempfile.mkstemp(suffix=ext, dir=IMG_DIR)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw)
    try:
        for maxdim, q in ((THUMB_W, 70), (THUMB_W, 55), (400, 65), (400, 45)):
            _sips(tmp, out_path, maxdim, q)
            size = os.path.getsize(out_path)
            if size <= MAX_BYTES:
                return size, maxdim
        return os.path.getsize(out_path), 400
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------- 单条目抓取
def pick_license(meta, require_license=True):
    if not meta:
        return None
    if not license_ok(meta):
        return None
    return meta


def try_wiki_page(base, title, source_name):
    """走 pageimages，返回待补许可的 entry 原型（许可查询统一批量做，省请求）。"""
    hit = page_image(base, title)
    if not hit:
        return None
    return {
        'source': source_name,
        'title': hit['title'],
        'page_url': base.split('/w/')[0] + '/wiki/' + urllib.parse.quote(hit['title'].replace(' ', '_')),
        'thumb': hit['thumb'],
        'pending_file': hit['file'],
    }


def norm_file(t):
    return re.sub(r'\s+', ' ', str(t).replace('_', ' ')).strip()


def batch_file_meta(fnames, base, batch=40):
    """一次查多个 File: 的许可信息，返回 {规范化文件名: meta}。"""
    out = {}
    names = list(fnames)
    for i in range(0, len(names), batch):
        chunk = names[i:i + batch]
        try:
            data = api(base, {
                'action': 'query',
                'titles': '|'.join('File:' + f for f in chunk),
                'prop': 'imageinfo', 'iiprop': 'url|extmetadata|size',
                'iiextmetadatafilter': 'LicenseShortName|License|Artist|Credit|UsageTerms|Copyrighted|LicenseUrl',
            })
        except Exception:  # noqa: BLE001
            continue
        for p in (data.get('query', {}).get('pages') or []):
            if p.get('missing') or p.get('invalid'):
                continue
            ii = (p.get('imageinfo') or [{}])[0]
            if not ii:
                continue
            m = meta_of(ii.get('extmetadata') or {})
            m['descurl'] = ii.get('descriptionurl') or ''
            key = norm_file(p.get('title', '').replace('File:', ''))
            out[key] = m
    return out


def enrich_licenses(images):
    """批量补许可信息；拿不到许可的直接丢弃（含已下载的文件）。"""
    pend = [k for k, v in images.items() if not v.get('license') and v.get('pending_file')]
    if not pend:
        return
    found = {}
    for base in (COMMONS, ZH, EN):
        need = {}
        for k in pend:
            f = images[k]['pending_file']
            if norm_file(f) in found:
                continue
            need[norm_file(f)] = f
        if not need:
            break
        got = batch_file_meta(need.keys(), base)
        for k, m in got.items():
            found.setdefault(k, m)

    drop = []
    for k in pend:
        m = found.get(norm_file(images[k]['pending_file']))
        if not m or not license_ok(m):
            drop.append(k)
            continue
        images[k]['license'] = m['license']
        images[k]['author'] = m['author']
        images[k]['page_url'] = m.get('descurl') or images[k]['page_url']
    for k in drop:
        path = os.path.join(ROOT, images[k]['file'])
        try:
            os.remove(path)
        except OSError:
            pass
        images.pop(k, None)
    print('许可补齐：%d 条保留，%d 条丢弃' % (len(pend) - len(drop), len(drop)))


def try_commons(term, source_name='commons'):
    for cand in commons_search(term):
        if not license_ok(cand):
            continue
        return {
            'source': source_name,
            'title': cand['title'],
            'page_url': cand.get('page_url', ''),
            'license': cand['license'],
            'author': cand['author'],
            'thumb': cand['thumb'],
        }
    return None


def resolve(kind, item):
    """按 zh → en → commons 的顺序找图。item 是 data.js 里的对象。"""
    name = item['name']
    if kind == 'recipe':
        key = 'recipe:' + item['id']
        fname = 'recipe-%s.jpg' % item['id']
        order = [('zh', '中文维基百科', [name])]
        en_titles = EN_RECIPE.get(item['id']) or []
        if en_titles:
            order.append(('en', 'English Wikipedia', en_titles))
    else:
        key = 'ingredient:' + item['id']
        fname = 'ing-%s.jpg' % item['id']
        zh_title = ZH_ING.get(item['id'], name)
        cands = [zh_title]
        for a in (item.get('alias') or [])[:2]:
            if a and a != zh_title:
                cands.append(a)
        order = [('zh', '中文维基百科', cands)]
        en_titles = EN_ING.get(item['id']) or []
        if en_titles:
            order.append(('en', 'English Wikipedia', en_titles))

    for lang, src_name, titles in order:
        base = ZH if lang == 'zh' else EN
        for t in titles:
            got = try_wiki_page(base, t, src_name)
            if got:
                got['fname'] = fname
                return key, got

    # Commons 搜索：先用词条名，再用别名
    terms = [ZH_ING.get(item['id'], name)] if kind == 'ingredient' else [name]
    terms += (item.get('alias') or [])[:1]
    for t in terms:
        got = try_commons(t, '维基共享资源')
        if got:
            got['fname'] = fname
            return key, got
    return key, None


def worker(kind, item, existing):
    key = ('recipe:' if kind == 'recipe' else 'ingredient:') + item['id']
    if key in existing and os.path.exists(os.path.join(ROOT, existing[key]['file'])):
        return key, existing[key], 'skip'
    try:
        key, got = resolve(kind, item)
    except Exception as e:  # noqa: BLE001
        return key, None, 'err:' + str(e)[:80]
    if not got:
        return key, None, 'none'
    out_path = os.path.join(IMG_DIR, got['fname'])
    try:
        raw = download(got['thumb'])
        size, dim = save_jpeg(raw, out_path)
    except Exception as e:  # noqa: BLE001
        return key, None, 'dl:' + str(e)[:80]
    entry = {
        'file': 'images/' + got['fname'],
        'source': got['source'],
        'title': got['title'],
        'page_url': got.get('page_url') or '',
        'license': got.get('license') or '',
        'author': got.get('author') or '',
        'px': dim,
        'bytes': size,
    }
    if got.get('pending_file'):
        entry['pending_file'] = got['pending_file']
    return key, entry, 'ok'


# ---------------------------------------------------------------- 数据读取 / 输出
def load_db():
    src = open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    i = src.index('window.RECIPE_DB')
    j = src.index('{', i)
    db, _ = json.JSONDecoder().raw_decode(src[j:])
    return db


def load_images():
    if os.path.exists(OUT_JSON):
        try:
            return json.load(open(OUT_JSON, encoding='utf-8'))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def write_outputs(db, images):
    tmp = OUT_JSON + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(images, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')
    os.replace(tmp, OUT_JSON)

    with open(OUT_JS, 'w', encoding='utf-8') as f:
        f.write('/* 图片来源与许可 —— 由 fetch_images.py 生成，请勿手改 */\n')
        f.write('window.RECIPE_IMAGES = ')
        json.dump(images, f, ensure_ascii=False, indent=0, sort_keys=True)
        f.write(';\n')

    # 缺失清单
    miss_r = [r for r in db['recipes'] if 'recipe:' + r['id'] not in images]
    miss_i = [i for i in db['ingredients'] if 'ingredient:' + i['id'] not in images]
    total_b = sum(v.get('bytes', 0) for v in images.values())
    lines = [
        '# 未抓到配图的条目（前端仍用 emoji 占位）',
        '# 生成时间 %s' % time.strftime('%Y-%m-%d %H:%M:%S'),
        '# 菜谱命中 %d/%d，食材命中 %d/%d' % (
            len(db['recipes']) - len(miss_r), len(db['recipes']),
            len(db['ingredients']) - len(miss_i), len(db['ingredients'])),
        '',
        '## 菜谱（%d）' % len(miss_r),
    ]
    lines += ['%s\t%s' % (r['id'], r['name']) for r in miss_r]
    lines += ['', '## 食材（%d）' % len(miss_i)]
    lines += ['%s\t%s' % (i['id'], i['name']) for i in miss_i]
    with open(MISSING_TXT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    print('images.json: %d 条, 磁盘 %.1f MB' % (len(images), total_b / 1048576))
    return total_b


def shrink_if_needed(images):
    """总体积 > 40MB 时，把全部缩略图重压到 400px。"""
    total = sum(v.get('bytes', 0) for v in images.values())
    if total <= 40 * 1048576:
        return total, False
    print('!! 总体积 %.1f MB > 40MB，全部重压到 400px' % (total / 1048576))
    for k, v in images.items():
        path = os.path.join(ROOT, v['file'])
        if not os.path.exists(path):
            continue
        _sips(path, path, 400, 68)
        v['bytes'] = os.path.getsize(path)
        v['px'] = 400
    return sum(v.get('bytes', 0) for v in images.values()), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', choices=['recipe', 'ingredient'])
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--rebuild', action='store_true')
    args = ap.parse_args()

    os.makedirs(IMG_DIR, exist_ok=True)
    db = load_db()
    images = load_images()

    if args.rebuild:
        total = write_outputs(db, images)
        print('总计 %.2f MB' % (total / 1048576))
        return

    items = []
    if args.only != 'ingredient':
        items += [('recipe', r) for r in db['recipes']]
    if args.only != 'recipe':
        items += [('ingredient', i) for i in db['ingredients']]
    if args.limit:
        items = items[:args.limit]

    print('待处理 %d 条（已有 %d 条）' % (len(items), len(images)))
    from concurrent.futures import ThreadPoolExecutor, as_completed

    done = 0
    write_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(worker, k, it, images): (k, it) for k, it in items}
        for fut in as_completed(futs):
            key, entry, status = fut.result()
            done += 1
            with write_lock:
                if entry and status != 'skip':
                    images[key] = entry
                if done % 20 == 0 or status.startswith(('err', 'dl')):
                    print('[%d/%d] %s %s %s' % (done, len(items), key, status,
                                                (entry or {}).get('license', '')),
                          flush=True)
                if done % 50 == 0:
                    write_outputs(db, images)

    enrich_licenses(images)
    total, shrunk = shrink_if_needed(images)
    write_outputs(db, images)
    hits_r = sum(1 for r in db['recipes'] if 'recipe:' + r['id'] in images)
    hits_i = sum(1 for i in db['ingredients'] if 'ingredient:' + i['id'] in images)
    print('命中：菜谱 %d/%d，食材 %d/%d；请求 %d 次；总计 %.2f MB' % (
        hits_r, len(db['recipes']), hits_i, len(db['ingredients']),
        _stats['req'], total / 1048576))


if __name__ == '__main__':
    main()
