#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取菜品/食材照片（只用维基百科 pageimages + 维基共享资源缩略图）。

只依赖 Python 3 标准库（urllib / json / re）。

  python3 fetch_images.py                 # 全量，断点续跑
  python3 fetch_images.py --limit 20      # 只跑前 20 条，试水
  python3 fetch_images.py --force missing # 只重跑上次没命中的

输出：
  images/<recipe|ing>-<id>.jpg   600px 缩略图（单张 ≤120KB）
  images.json                    元数据（file/source/title/page_url/license/author）
  images-data.js                 window.RECIPE_IMAGES，双击 index.html 也能用
  missing-images.txt             没抓到图的条目
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(ROOT, 'images')
OUT_JSON = os.path.join(ROOT, 'images.json')
OUT_JS = os.path.join(ROOT, 'images-data.js')
OUT_MISSING = os.path.join(ROOT, 'missing-images.txt')

ZH = 'https://zh.wikipedia.org/w/api.php'
EN = 'https://en.wikipedia.org/w/api.php'
COMMONS = 'https://commons.wikimedia.org/w/api.php'

UA = 'RecipeAppPhotoFetcher/1.0 (local offline cooking demo; contact: local user)'
MIN_GAP = 0.9          # 全局限速：两次 API 请求之间至少 0.9s（维基对共享出口 IP 限流）
DL_GAP = 0.55          # 图片下载间隔（upload.wikimedia.org 也会 429）
MAX_BYTES = 120 * 1024  # 单张上限 120KB

_lock = threading.Lock()
_last = [0.0]
N429 = [0]


def throttle(gap=MIN_GAP):
    """全局串行节流，所有线程共享一个最小间隔。"""
    with _lock:
        wait = gap - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def api(base, params, tries=4, gap=MIN_GAP):
    params = dict(params)
    params.setdefault('format', 'json')
    params.setdefault('formatversion', '2')
    url = base + '?' + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(tries):
        throttle(gap)
        req = urllib.request.Request(url, headers={
            'User-Agent': UA,
            'Accept': 'application/json',
            'Accept-Encoding': 'identity',
        })
        try:
            with urllib.request.urlopen(req, timeout=9) as resp:
                return json.loads(resp.read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                N429[0] += 1
                try:
                    wait = float(e.headers.get('Retry-After') or 0)
                except (TypeError, ValueError):
                    wait = 0.0
                time.sleep(max(wait, 3.0) + 0.6 * (attempt + 1))
                continue
            if e.code in (403, 404, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as e:  # noqa: BLE001  网络抖动
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    if last_err:
        raise last_err
    return {}


def strip_html(s):
    s = re.sub(r'<[^>]+>', '', str(s or ''))
    s = (s.replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
          .replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' '))
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:120]


def meta_of(em):
    def pick(*keys):
        for k in keys:
            v = (em.get(k) or {})
            val = v.get('value') if isinstance(v, dict) else v
            if val:
                return strip_html(val)
        return ''
    lic = pick('LicenseShortName', 'License', 'UsageTerms') or ''
    if not lic:
        if str(pick('Copyrighted')).lower() == 'true':
            lic = 'non-free'
        else:
            lic = 'unknown'
    return {'license': lic, 'author': pick('Artist', 'Credit', 'Attribution') or '未知作者'}


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



# ---------------------------------------------------------------- 食材 → 英文名（补充表，229 条）
EN_ING_EXTRA = {
    'eggplant': ['Eggplant'], 'cucumber': ['Cucumber'], 'daikon': ['Daikon'], 'carrot': ['Carrot'],
    'spinach': ['Spinach'], 'celery': ['Celery'], 'chives': ['Garlic chives'], 'chive_sprout': ['Yellow chives'],
    'bean_sprout': ['Mung bean sprout'], 'soy_sprout': ['Soybean sprout'], 'garlic_sprout': ['Garlic sprout'],
    'green_pepper': ['Green bell pepper'], 'red_pepper': ['Red bell pepper'], 'hot_pepper': ["Bird's eye chili"],
    'bell_pepper': ['Bell pepper'], 'pumpkin': ['Pumpkin'], 'zucchini': ['Zucchini'],
    'water_chestnut': ['Water chestnut'], 'bamboo_shoot': ['Bamboo shoot'], 'asparagus_lettuce': ['Celtuce'],
    'cabbage': ['Cabbage'], 'purple_cabbage': ['Red cabbage'], 'broccoli': ['Broccoli'], 'cauliflower': ['Cauliflower'],
    'romaine': ['Lettuce'], 'coriander': ['Coriander'], 'fennel': ['Fennel'], 'toon': ['Toona sinensis'],
    'rape': ['Choy sum'], 'mustard_green': ['Mustard greens'], 'amaranth': ['Amaranth'],
    'chrysanthemum': ['Garland chrysanthemum'], 'pea_shoot': ['Pea shoot'], 'green_beans': ['Green bean'],
    'basil': ['Basil'], 'pork_loin': ['Pork loin'], 'pork_mince': ['Ground pork'], 'pork_liver': ['Pork liver'],
    'pork_kidney': ['Pork kidney'], 'pork_intestine': ['Pork intestine'], 'pork_skin': ['Pork rind'],
    'pork_blood': ['Pig blood'], 'pork_shoulder': ['Pork shoulder'], 'lean_pork': ['Pork'],
    'beef_shank': ['Beef shank'], 'beef_sirloin': ['Beef tenderloin'], 'beef_mince': ['Ground beef'],
    'beef_tripe': ['Beef tripe'], 'beef_tail': ['Oxtail'], 'beef_ribs': ['Beef ribs'], 'beef_roll': ['Beef roll'],
    'lamb_leg': ['Lamb and mutton'], 'lamb_chop': ['Lamb chop'], 'lamb_roll': ['Lamb and mutton'],
    'chicken_whole': ['Chicken as food'], 'chicken_breast': ['Chicken breast'], 'chicken_mince': ['Ground chicken'],
    'chicken_bones': ['Chicken carcass'], 'duck_breast': ['Duck as food'], 'duck_wing': ['Duck as food'],
    'duck_neck': ['Duck as food'], 'rabbit': ['Rabbit as food'], 'pigeon': ['Squab'], 'spam': ['Spam (food)'],
    'quail': ['Quail'], 'grass_carp': ['Grass carp'], 'crucian_carp': ['Crucian carp'], 'silver_carp': ['Silver carp'],
    'bighead_carp': ['Bighead carp'], 'yellow_croaker': ['Yellow croaker'], 'hairtail': ['Largehead hairtail'],
    'tilapia': ['Tilapia'], 'eel': ['Eel'], 'loach': ['Pond loach'], 'snakehead': ['Snakehead'],
    'catfish': ['Catfish'], 'mandarin_fish': ['Mandarin fish'], 'river_shrimp': ['Shrimp'],
    'mud_crab': ['Mud crab'], 'cuttlefish': ['Cuttlefish'], 'octopus': ['Octopus'], 'clam': ['Clam'],
    'razor_clam': ['Razor clam'], 'mussel': ['Mussel'], 'fish_ball': ['Fish ball'], 'fish_tofu': ['Fish ball'],
    'crab_stick': ['Crab stick'], 'duck_egg': ['Duck egg'], 'cream': ['Cream'],
    'condensed_milk': ['Condensed milk'], 'coconut_milk': ['Coconut milk'], 'egg_white': ['Egg white'],
    'egg_yolk': ['Egg yolk'], 'milk_powder': ['Milk powder'], 'silken_tofu': ['Tofu'], 'dried_tofu': ['Tofu'],
    'tofu_skin': ['Yuba'], 'fried_tofu': ['Tofu'], 'yuba': ['Yuba'], 'soybean': ['Soybean'],
    'black_bean': ['Black soybean'], 'mung_bean': ['Mung bean'], 'red_bean': ['Adzuki bean'],
    'edamame': ['Edamame'], 'fermented_tofu': ['Fermented bean curd'], 'soy_milk': ['Soy milk'],
    'tofu_pudding': ['Douhua'], 'konjac': ['Konjac'], 'seitan': ['Wheat gluten'], 'veg_chicken': ['Tofu'],
    'frozen_tofu': ['Tofu'], 'tofu_shred': ['Tofu'], 'thousand_tofu': ['Tofu'], 'chickpea': ['Chickpea'],
    'kidney_bean': ['Kidney bean'], 'pea': ['Pea'], 'broad_bean': ['Broad bean'], 'cooked_rice': ['Cooked rice'],
    'black_rice': ['Black rice'], 'oats': ['Oat'], 'high_gluten_flour': ['Wheat flour'],
    'low_gluten_flour': ['Wheat flour'], 'glutinous_flour': ['Glutinous rice flour'], 'rice_noodle': ['Rice noodles'],
    'sweet_potato_noodle': ['Cellophane noodles'], 'fresh_noodle': ['Noodle'], 'instant_noodle': ['Instant noodles'],
    'dumpling_wrapper': ['Jiaozi'], 'wonton_wrapper': ['Wonton'], 'cornmeal': ['Cornmeal'],
    'buckwheat_noodle': ['Soba'], 'rice_noodle_roll': ['Shahe fen'], 'sago': ['Sago'],
    'hand_pancake': ['Cong you bing'], 'rice_roll': ['Rice noodle roll'], 'guoba': ['Guoba'],
    'salt': ['Salt'], 'sugar': ['White sugar'], 'brown_sugar': ['Brown sugar'], 'dark_soy': ['Soy sauce'],
    'black_vinegar': ['Vinegar'], 'white_vinegar': ['Vinegar'], 'peanut_oil': ['Peanut oil'],
    'rapeseed_oil': ['Rapeseed oil'], 'corn_oil': ['Corn oil'], 'olive_oil': ['Olive oil'], 'lard': ['Lard'],
    'scallion_oil': ['Scallion oil'], 'bean_paste': ['Doubanjiang'], 'sweet_bean_sauce': ['Sweet bean sauce'],
    'yellow_bean_sauce': ['Soybean paste'], 'hoisin_sauce': ['Hoisin sauce'], 'chili_sauce': ['Chili sauce'],
    'garlic_chili_sauce': ['Chili sauce'], 'fermented_chili': ['Chili pepper'], 'pickled_pepper': ['Pao cai'],
    'black_pepper': ['Black pepper'], 'white_pepper': ['White pepper'], 'five_spice': ['Five-spice powder'],
    'thirteen_spice': ['Five-spice powder'], 'cumin': ['Cumin'], 'chili_powder': ['Chili powder'],
    'curry_powder': ['Curry powder'], 'curry_cube': ['Curry'], 'potato_starch': ['Potato starch'],
    'baking_soda': ['Sodium bicarbonate'], 'baking_powder': ['Baking powder'], 'yeast': ['Yeast'],
    'chicken_bouillon': ['Bouillon cube'], 'msg': ['Monosodium glutamate'], 'maltose': ['Maltose'],
    'sesame': ['Sesame'], 'peanut_butter': ['Peanut butter'], 'sesame_paste': ['Tahini'],
    'fish_sauce': ['Fish sauce'], 'ketchup': ['Ketchup'], 'mayonnaise': ['Mayonnaise'],
    'mustard': ['Mustard (condiment)'], 'star_anise': ['Star anise'], 'cinnamon': ['Cinnamon'],
    'bay_leaf': ['Bay leaf'], 'dried_chili': ['Chili pepper'], 'fennel_seed': ['Fennel'], 'clove': ['Clove'],
    'cardamom': ['Cardamom'], 'seasoned_soy': ['Soy sauce'], 'char_siu_sauce': ['Char siu'],
    'sweet_osmanthus': ['Osmanthus'], 'sichuan_pepper_oil': ['Sichuan pepper'], 'douchi': ['Douchi'],
    'shrimp_paste': ['Shrimp paste'], 'soup_stock': ['Stock (food)'], 'fermented_rice': ['Jiuniang'],
    'dried_mushroom': ['Shiitake'], 'white_fungus': ['Tremella fuciformis'], 'oyster_mushroom': ['Pleurotus ostreatus'],
    'king_oyster': ['Pleurotus eryngii'], 'button_mushroom': ['Agaricus bisporus'],
    'straw_mushroom': ['Straw mushroom'], 'tea_tree_mushroom': ['Agrocybe aegerita'],
    'bamboo_fungus': ['Phallus indusiatus'], 'morel': ['Morchella'], 'porcini': ['Boletus edulis'],
    'cordyceps_flower': ['Cordyceps militaris'], 'matsutake': ['Matsutake'], 'nori': ['Nori'],
    'dried_shrimp': ['Dried shrimp'], 'dried_scallop': ['Scallop'], 'dried_squid': ['Squid'],
    'salted_fish': ['Salted fish'], 'dried_whitebait': ['Whitebait'], 'preserved_veg': ['Meigan cai'],
    'pickled_cabbage': ['Suancai'], 'zhacai': ['Zha cai'], 'dried_bamboo': ['Bamboo shoot'],
    'tangerine_peel': ['Chenpi'], 'almond': ['Almond'], 'pine_nut': ['Pine nut'], 'dried_longan': ['Longan'],
    'dried_lily': ['Lilium'], 'job_tears': ["Job's tears"], 'daylily': ['Daylily'], 'dried_radish': ['Daikon'],
    'fish_maw': ['Fish maw'], 'cream_cheese': ['Cream cheese'], 'mozzarella': ['Mozzarella'],
    'salted_yolk': ['Salted duck egg'], 'evaporated_milk': ['Evaporated milk'], 'yacai': ['Ya cai'],
}


RE_LICENSE_BAD = re.compile(r'fair use|non-free|nonfree|all rights reserved|copyright', re.I)
RE_LICENSE_OK = re.compile(r'cc[- ]?by|cc0|public domain|pd-|gfdl|free art|attribution|share[- ]?alike', re.I)


def license_ok(meta):
    lic = str(meta.get('license') or '')
    if not lic or lic == 'unknown':
        return False
    if RE_LICENSE_BAD.search(lic):
        return False
    return bool(RE_LICENSE_OK.search(lic))


def norm_title(t):
    t = str(t or '').replace('_', ' ')
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:1].upper() + t[1:] if t else t


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def batch_page_images(titles, base, batch=40):
    """批量查 pageimages，返回 {请求标题: {title, file, thumb}}。"""
    out = {}
    uniq = [norm_title(t) for t in titles if t]
    uniq = list(dict.fromkeys(uniq))
    for chunk in chunks(uniq, batch):
        try:
            data = api(base, {
                'action': 'query',
                'titles': '|'.join(chunk),
                'prop': 'pageimages',
                'pithumbsize': 600,
                'redirects': '1',
            }, gap=1.1)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write('  ! batch failed (%d titles): %s\n' % (len(chunk), e))
            continue
        q = data.get('query', {}) or {}
        pages = {p.get('title'): p for p in (q.get('pages') or [])}
        alias = {}
        for n in (q.get('normalized') or []):
            alias[n.get('from')] = n.get('to')
        for r in (q.get('redirects') or []):
            alias[r.get('from')] = r.get('to')
        for t in chunk:
            cur, hops = t, 0
            while cur in alias and hops < 5:
                cur, hops = alias[cur], hops + 1
            p = pages.get(cur)
            if not p or p.get('missing') or p.get('invalid'):
                continue
            th = ((p.get('thumbnail') or {}).get('source') or '').split('?')[0]
            if not th or re.search(r'\.(svg|gif|tiff?)$', th, re.I):
                continue
            out[t] = {'title': p.get('title') or t, 'file': p.get('pageimage') or '', 'thumb': th}
    return out


def batch_file_meta(fnames, base, batch=40):
    """批量查 File: 的许可信息，返回 {规范化文件名: {license, author, descurl}}。"""
    out = {}
    uniq = list(dict.fromkeys(f for f in fnames if f))
    for chunk in chunks(uniq, batch):
        try:
            data = api(base, {
                'action': 'query',
                'titles': '|'.join('File:' + f for f in chunk),
                'prop': 'imageinfo',
                'iiprop': 'url|extmetadata|size',
                'iiextmetadatafilter': ('LicenseShortName|License|Artist|Credit|UsageTerms|'
                                        'Copyrighted|LicenseUrl|Attribution'),
            }, gap=1.1)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write('  ! license batch failed: %s\n' % e)
            continue
        for p in ((data.get('query') or {}).get('pages') or []):
            if p.get('missing') or p.get('invalid'):
                continue
            ii = (p.get('imageinfo') or [{}])[0] or {}
            m = meta_of(ii.get('extmetadata') or {})
            m['descurl'] = ii.get('descriptionurl') or ''
            out[norm_title('File:' + p.get('title', '').replace('File:', ''))[5:]] = m
    return out


def commons_search(term, limit=3):
    """Commons 搜索图片（必须一条一请求），返回候选列表。"""
    try:
        data = api(COMMONS, {
            'action': 'query',
            'generator': 'search',
            'gsrsearch': term,
            'gsrnamespace': '6',
            'gsrlimit': str(limit),
            'prop': 'imageinfo',
            'iiprop': 'url|extmetadata|size',
            'iiurlwidth': '600',
        }, gap=1.1, tries=1)
    except Exception:  # noqa: BLE001
        return []
    q = data.get('query', {}) or {}
    pages = q.get('pages') or []
    pages.sort(key=lambda p: p.get('index') or 99)
    out = []
    for p in pages:
        title = p.get('title') or ''
        if not re.search(r'\.(jpe?g|png|webp)$', title, re.I):
            continue
        ii = (p.get('imageinfo') or [{}])[0] or {}
        thumb = (ii.get('thumburl') or ii.get('url') or '').split('?')[0]
        if not thumb:
            continue
        m = meta_of(ii.get('extmetadata') or {})
        if not license_ok(m):
            continue
        out.append({
            'source': 'commons.wikimedia.org',
            'title': title.replace('File:', '').replace('_', ' '),
            'page_url': ii.get('descriptionurl') or '',
            'license': m['license'],
            'author': m['author'],
            'thumb': thumb,
        })
    return out


RE_STOP = re.compile(r'^(the|and|as|of|in|with|a|an|food|dish|raw)$', re.I)


def title_score(term, title, zh_name=''):
    """相关性打分：词条里的实词在文件名里出现才算命中，避免随便配图。"""
    t = title.lower()
    score = 0
    if zh_name and zh_name in title:
        score += 5
    words = [w for w in re.split(r'[^A-Za-z0-9]+', term) if len(w) >= 3 and not RE_STOP.match(w)]
    for w in words:
        if w.lower() in t:
            score += 2
    if re.search(r'\bcomposite\b|\bmontage\b|\bmap\b|\blogo\b|\bicon\b', t):
        score -= 3
    return score


def _dl_once(url):
    out = {}

    def run():
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=10) as resp:
                out['data'] = resp.read()
        except Exception as e:  # noqa: BLE001
            out['err'] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(15)
    if 'data' in out:
        return out['data']
    raise out.get('err') or TimeoutError('download timed out')


def download(url, tries=3):
    last = None
    for attempt in range(tries):
        throttle(DL_GAP)
        try:
            return _dl_once(url)
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                N429[0] += 1
                try:
                    wait = float(e.headers.get('Retry-After') or 0)
                except (TypeError, ValueError):
                    wait = 0.0
                time.sleep(min(max(wait, 1.5), 5.0) + 0.6 * (attempt + 1))
                continue
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0 * (attempt + 1))
    raise last


def sips_resize(data, path, maxpx, quality):
    tmp = path + '.raw'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    subprocess.run(['sips', '-Z', str(maxpx), '-s', 'format', 'jpeg',
                    '-s', 'formatOptions', str(quality), tmp, '--out', path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.remove(tmp)
    return os.path.getsize(path)


def save_image(data, path):
    """写盘并压到 ≤120KB：600/q70 → 600/q55 → 400/q65 → 400/q45。"""
    if os.path.exists(path):
        os.remove(path)
    last = None
    for maxpx, quality in ((600, 70), (600, 55), (400, 65), (400, 45)):
        try:
            size = sips_resize(data, path, maxpx, quality)
        except subprocess.CalledProcessError:
            if os.path.exists(path):
                os.remove(path)
            return None, None
        last = (maxpx, size)
        if size <= MAX_BYTES:
            break
    if not last:
        return None, None
    return last


def load_db():
    src = open(os.path.join(ROOT, 'data.js'), encoding='utf-8').read()
    m = re.search(r'window\.RECIPE_DB\s*=\s*', src)
    if not m:
        raise SystemExit('data.js 里找不到 window.RECIPE_DB')
    obj, _ = json.JSONDecoder().raw_decode(src[m.end():].lstrip())
    return obj


def load_images():
    if os.path.exists(OUT_JSON):
        try:
            with open(OUT_JSON, encoding='utf-8') as fh:
                data = json.load(fh)
            return {k: v for k, v in data.items() if isinstance(v, dict) and v.get('file')}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def write_outputs(db, images):
    ordered = dict(sorted(images.items()))
    with open(OUT_JSON, 'w', encoding='utf-8') as fh:
        json.dump(ordered, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    with open(OUT_JS, 'w', encoding='utf-8') as fh:
        fh.write('/* 自动生成：python3 fetch_images.py。图片与许可信息见 images.json */\n')
        fh.write('window.RECIPE_IMAGES = ')
        json.dump(ordered, fh, ensure_ascii=False, separators=(',', ':'))
        fh.write(';\n')

    miss = []
    for r in db['recipes']:
        if ('recipe:' + r['id']) not in images:
            miss.append('recipe\t%s\t%s' % (r['id'], r.get('name', '')))
    for i in db['ingredients']:
        if ('ingredient:' + i['id']) not in images:
            miss.append('ingredient\t%s\t%s' % (i['id'], i.get('name', '')))
    with open(OUT_MISSING, 'w', encoding='utf-8') as fh:
        fh.write('类型\tid\t名称\n')
        fh.write('\n'.join(miss) + ('\n' if miss else ''))
    return len(miss)


def shrink_if_needed(images):
    total = 0
    for v in images.values():
        try:
            total += os.path.getsize(os.path.join(ROOT, v['file']))
        except OSError:
            pass
    return total


def main():
    argv = sys.argv[1:]
    limit = None
    force = None
    workers = 2
    no_commons = '--no-commons' in argv
    for i, a in enumerate(argv):
        if a == '--limit' and i + 1 < len(argv):
            limit = int(argv[i + 1])
        if a == '--workers' and i + 1 < len(argv):
            workers = int(argv[i + 1])
        if a == '--force' and i + 1 < len(argv):
            force = argv[i + 1]

    os.makedirs(IMG_DIR, exist_ok=True)
    db = load_db()
    images = load_images()
    miss_prev = set()
    if force == 'missing' and os.path.exists(OUT_MISSING):
        for line in open(OUT_MISSING, encoding='utf-8').read().splitlines()[1:]:
            parts = line.split('\t')
            if len(parts) >= 2:
                miss_prev.add(parts[0] + ':' + parts[1])

    items = []
    for r in db['recipes']:
        items.append(('recipe', r['id'], r.get('name', ''), EN_RECIPE.get(r['id'], [])))
    for i in db['ingredients']:
        items.append(('ingredient', i['id'], i.get('name', ''),
                      EN_ING.get(i['id']) or EN_ING_EXTRA.get(i['id']) or []))

    todo = []
    for kind, oid, name, en in items:
        key = kind + ':' + oid
        if key in images:
            continue
        if miss_prev and key not in miss_prev:
            continue
        todo.append((kind, oid, name, en))
    if limit:
        todo = todo[:limit]
    print('待处理 %d 条（已有 %d 条图片）' % (len(todo), len(images)))

    # ---------- 1. 中文维基批量解析 ----------
    zh_titles = {}
    for kind, oid, name, en in todo:
        cands = []
        if kind == 'ingredient':
            cands = [ZH_ING.get(oid) or name] + [name]
        else:
            cands = [name]
        cands = [norm_title(c) for c in cands if c]
        zh_titles[(kind, oid)] = list(dict.fromkeys(cands))
    all_zh = [t for v in zh_titles.values() for t in v]
    print('· 中文维基批量查询 %d 个词条…' % len(set(all_zh)))
    zh_hits = batch_page_images(all_zh, ZH)

    plan = {}
    for kind, oid, name, en in todo:
        for t in zh_titles[(kind, oid)]:
            hit = zh_hits.get(t)
            if hit:
                plan[(kind, oid)] = {
                    'source': 'zh.wikipedia.org',
                    'title': hit['title'],
                    'page_url': 'https://zh.wikipedia.org/wiki/' + urllib.parse.quote(hit['title'].replace(' ', '_')),
                    'thumb': hit['thumb'],
                    'pending_file': hit['file'],
                }
                break
    print('  中文命中 %d 条' % len(plan))

    # ---------- 2. 英文维基批量兜底 ----------
    en_titles = {}
    for kind, oid, name, en in todo:
        if (kind, oid) in plan or not en:
            continue
        en_titles[(kind, oid)] = [norm_title(t) for t in en][:3]
    all_en = [t for v in en_titles.values() for t in v]
    if all_en:
        print('· 英文维基批量查询 %d 个词条…' % len(set(all_en)))
        en_hits = batch_page_images(all_en, EN)
        for (kind, oid), cands in en_titles.items():
            for t in cands:
                hit = en_hits.get(t)
                if hit:
                    plan[(kind, oid)] = {
                        'source': 'en.wikipedia.org',
                        'title': hit['title'],
                        'page_url': 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(hit['title'].replace(' ', '_')),
                        'thumb': hit['thumb'],
                        'pending_file': hit['file'],
                    }
                    break
        print('  英文补上 %d 条（累计命中 %d）' % (len(en_titles), len(plan)))

    # ---------- 3. Commons 搜索兜底 ----------
    rest = [] if no_commons else [x for x in todo if (x[0], x[1]) not in plan]
    if rest:
        print('· Commons 搜索兜底 %d 条（一条一请求，慢）…' % len(rest))
    t_commons = time.time()
    for idx, (kind, oid, name, en) in enumerate(rest):
        if time.time() - t_commons > 100:
            print('  （Commons 搜索超时预算，跳过剩余 %d 条）' % (len(rest) - idx))
            break
        if N429[0] > 4:
            print('  （共享出口被限流，跳过剩余 Commons 搜索）')
            break
        terms = [name] + [e for e in (en or [])[:2] if e]
        seen_terms, uniq_terms = set(), []
        for t in terms:
            if t and t not in seen_terms:
                seen_terms.add(t)
                uniq_terms.append(t)
        for term in uniq_terms:
            cands = commons_search(term, 4)
            if not cands:
                continue
            pick, best = None, 0
            for c in cands:
                score = title_score(term, c['title'], name)
                if score > best:
                    pick, best = c, score
            if pick:
                plan[(kind, oid)] = pick
                break
        if idx % 20 == 19:
            print('  commons %d/%d' % (idx + 1, len(rest)))
    print('  解析完成：%d/%d' % (len(plan), len(todo)))

    # ---------- 4. 下载 ----------
    jobs = []
    for (kind, oid), got in plan.items():
        fname = ('recipe-' if kind == 'recipe' else 'ing-') + str(oid) + '.jpg'
        jobs.append((kind, oid, fname, got))

    done = [0]
    lock = threading.Lock()

    def work(job):
        kind, oid, fname, got = job
        key = kind + ':' + str(oid)
        path = os.path.join(IMG_DIR, fname)
        reused = os.path.exists(path) and os.path.getsize(path) > 2048
        try:
            if reused:
                data = None
            else:
                data = download(got['thumb'])
        except Exception as e:  # noqa: BLE001
            with lock:
                done[0] += 1
            return key, 'dl:%s' % e
        px, size = (600, os.path.getsize(path)) if reused else save_image(data, path)
        with lock:
            done[0] += 1
            n = done[0]
        if not px or size < 2048:
            return key, 'tiny'
        entry = {
            'file': 'images/' + fname,
            'source': got['source'],
            'title': got['title'],
            'page_url': got.get('page_url') or '',
            'license': got.get('license') or '',
            'author': got.get('author') or '',
            'px': px,
            'bytes': size,
        }
        if got.get('pending_file'):
            entry['pending_file'] = got['pending_file']
        if n % 40 == 0:
            print('  下载 %d/%d' % (n, len(jobs)))
        return key, entry

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (key, res) in enumerate(ex.map(work, jobs), 1):
            if isinstance(res, dict):
                images[key] = res
            if isinstance(res, str):
                sys.stderr.write('  skip %s (%s)\n' % (key, res))
            if i % 25 == 0:
                write_outputs(db, images)

    # ---------- 5. 批量补许可 ----------
    pend = [k for k, v in images.items() if not v.get('license') and v.get('pending_file')]
    if pend:
        print('· 补许可信息 %d 张（批量）…' % len(pend))
        found = {}
        for base in (COMMONS, ZH, EN):
            need = []
            for k in pend:
                f = images[k]['pending_file']
                if norm_title(f) not in found:
                    need.append(f)
            if not need:
                break
            got = batch_file_meta(need, base)
            for k2, v2 in got.items():
                found.setdefault(norm_title(k2), v2)
        drop = []
        for k in pend:
            m = found.get(norm_title(images[k]['pending_file']))
            if not m or not license_ok(m):
                drop.append(k)
                continue
            images[k]['license'] = m['license']
            images[k]['author'] = m['author']
            images[k]['page_url'] = m.get('descurl') or images[k].get('page_url') or ''
            images[k].pop('pending_file', None)
        for k in drop:
            try:
                os.remove(os.path.join(ROOT, images[k]['file']))
            except OSError:
                pass
            images.pop(k, None)
        print('  保留 %d，丢弃 %d' % (len(pend) - len(drop), len(drop)))

    for v in images.values():
        v.pop('pending_file', None)

    total = shrink_if_needed(images)
    nmiss = write_outputs(db, images)
    nrec = len([k for k in images if k.startswith('recipe:')])
    ning = len([k for k in images if k.startswith('ingredient:')])
    print('\nimages.json: %d 条, 磁盘 %.1f MB' % (len(images), total / 1048576.0))
    print('命中：菜谱 %d/%d，食材 %d/%d；未命中 %d' % (
        nrec, len(db['recipes']), ning, len(db['ingredients']), nmiss))
    print('缺图清单：%s' % OUT_MISSING)




if __name__ == "__main__":
    main()
