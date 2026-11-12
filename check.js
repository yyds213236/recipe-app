#!/usr/bin/env node
/* ===========================================================
   check.js —— 菜谱数据自检脚本
   用法：
     node check.js                 # 命令行跑，输出报告
     node check.js --json          # 输出 JSON
   也可把下面 check() 函数粘到浏览器控制台（data.js 已加载时）。
   =========================================================== */
'use strict';

function loadDB() {
  if (typeof window !== 'undefined' && window.RECIPE_DB) return window.RECIPE_DB;
  const fs = require('fs');
  const path = require('path');
  const file = path.join(__dirname, 'data.js');
  const src = fs.readFileSync(file, 'utf8');
  const sandbox = { window: {} };
  const fn = new Function('window', src + '\nreturn window.RECIPE_DB;');
  return fn(sandbox.window);
}

function check(db) {
  const errors = [];
  const warns = [];
  const ingredients = db.ingredients || [];
  const recipes = db.recipes || [];
  const byId = new Map();
  const CATS = ['蔬菜', '肉禽', '水产', '蛋奶', '豆制品', '主食', '调料', '干货/菌菇'];

  // ---- 食材库 ----
  ingredients.forEach((ing, i) => {
    if (!ing.id) errors.push(`食材 #${i} 缺少 id`);
    if (byId.has(ing.id)) errors.push(`食材 id 重复：${ing.id}`);
    byId.set(ing.id, ing);
    ['name', 'category', 'unit', 'emoji'].forEach((k) => {
      if (!ing[k]) errors.push(`食材 ${ing.id} 缺少字段 ${k}`);
    });
    if (!CATS.includes(ing.category)) errors.push(`食材 ${ing.id} 分类不在 8 类内：${ing.category}`);
    if (!Array.isArray(ing.alias)) errors.push(`食材 ${ing.id} 的 alias 不是数组`);
  });

  const catCount = {};
  CATS.forEach((c) => { catCount[c] = 0; });
  ingredients.forEach((i) => { catCount[i.category] = (catCount[i.category] || 0) + 1; });

  // ---- 菜谱 ----
  const recIds = new Set();
  const TAGSET = ['快手', '素菜', '汤', '下饭', '宴客', '早餐'];
  const usedIngredients = new Set();
  let totalRefs = 0;

  recipes.forEach((r) => {
    if (recIds.has(r.id)) errors.push(`菜谱 id 重复：${r.id}`);
    recIds.add(r.id);

    ['name', 'emoji', 'cuisine', 'time', 'difficulty', 'servings'].forEach((k) => {
      if (r[k] === undefined || r[k] === '') errors.push(`菜谱 ${r.id} 缺少字段 ${k}`);
    });
    if (!Array.isArray(r.tags) || !r.tags.length) errors.push(`菜谱 ${r.id} 没有 tags`);
    (r.tags || []).forEach((t) => {
      if (!TAGSET.includes(t)) errors.push(`菜谱 ${r.id} 的 tag 不在允许集合内：${t}`);
    });
    if (!(r.difficulty >= 1 && r.difficulty <= 3)) errors.push(`菜谱 ${r.id} difficulty 越界：${r.difficulty}`);
    if (!Array.isArray(r.steps) || r.steps.length < 4 || r.steps.length > 8) {
      errors.push(`菜谱 ${r.id} 步骤数 ${r.steps ? r.steps.length : 0} 不在 4–8 之间`);
    }
    (r.steps || []).forEach((s, i) => {
      const n = [...s].length;
      if (n < 15 || n > 60) errors.push(`菜谱 ${r.id} 第 ${i + 1} 步长度 ${n} 字，超出 15–60`);
    });
    if (!Array.isArray(r.ingredients) || !r.ingredients.length) {
      errors.push(`菜谱 ${r.id} 没有食材`);
      return;
    }

    const seen = new Set();
    let core = 0;
    (r.ingredients || []).forEach((g) => {
      totalRefs++;
      if (!g.id) { errors.push(`菜谱 ${r.id} 有食材缺少 id`); return; }
      if (!byId.has(g.id)) {
        errors.push(`菜谱 ${r.id} 引用了不存在的食材 id：${g.id}`);
        return;
      }
      if (seen.has(g.id)) errors.push(`菜谱 ${r.id} 食材重复：${g.id}`);
      seen.add(g.id);
      usedIngredients.add(g.id);
      if (typeof g.amount !== 'number' || !(g.amount > 0)) {
        errors.push(`菜谱 ${r.id} 的 ${g.id} 用量非法：${g.amount}`);
      }
      if (!g.unit) errors.push(`菜谱 ${r.id} 的 ${g.id} 缺少单位`);
      if (byId.get(g.id).category !== '调料') core++;
    });
    if (core === 0) warns.push(`菜谱 ${r.id} 没有「调料」以外的食材`);

    // 分类覆盖
  });

  // ---- 别名冲突检查 ----
  const aliasOwner = new Map();
  ingredients.forEach((ing) => {
    [ing.name].concat(ing.alias || []).forEach((a) => {
      if (!a) return;
      if (aliasOwner.has(a) && aliasOwner.get(a) !== ing.id) {
        warns.push(`别名「${a}」同时指向 ${aliasOwner.get(a)} 与 ${ing.id}`);
      } else aliasOwner.set(a, ing.id);
    });
  });

  // ---- 标签分布 ----
  const tagCount = {};
  recipes.forEach((r) => (r.tags || []).forEach((t) => { tagCount[t] = (tagCount[t] || 0) + 1; }));

  const cuisineCount = {};
  recipes.forEach((r) => { cuisineCount[r.cuisine] = (cuisineCount[r.cuisine] || 0) + 1; });

  return {
    ok: errors.length === 0,
    summary: {
      ingredients: ingredients.length,
      recipes: recipes.length,
      ingredientRefs: totalRefs,
      unusedIngredients: ingredients.length - usedIngredients.size
    },
    catCount, tagCount, cuisineCount,
    errors, warns
  };
}

const report = check(loadDB());

if (process.argv.includes('--json')) {
  console.log(JSON.stringify(report, null, 2));
} else {
  const line = '─'.repeat(52);
  console.log(line);
  console.log('  小锅菜谱 · 数据校验报告');
  console.log(line);
  console.log(`食材总数      ${report.summary.ingredients}`);
  console.log(`菜谱总数      ${report.summary.recipes}`);
  console.log(`食材引用次数  ${report.summary.ingredientRefs}`);
  console.log(`未被用到的食材 ${report.summary.unusedIngredients}`);
  console.log(line);
  console.log('分类分布：');
  Object.entries(report.catCount).forEach(([k, v]) => console.log(`  ${k.padEnd(6, '　')} ${v}`));
  console.log(line);
  console.log('标签分布：');
  Object.entries(report.tagCount).forEach(([k, v]) => console.log(`  ${k.padEnd(4, '　')} ${v}`));
  console.log(line);
  console.log('菜系分布：');
  Object.entries(report.cuisineCount).forEach(([k, v]) => console.log(`  ${k.padEnd(4, '　')} ${v}`));
  console.log(line);
  console.log(`错误  ${report.errors.length} 条`);
  report.errors.slice(0, 40).forEach((e) => console.log('  ✗ ' + e));
  console.log(`提醒  ${report.warns.length} 条`);
  report.warns.slice(0, 20).forEach((w) => console.log('  ! ' + w));
  console.log(line);
  console.log(report.ok ? '✓ 校验通过：所有菜谱引用的食材 id 都存在于食材库' : '✗ 校验失败，请修复上面的错误');
  console.log(line);
}

if (typeof module !== 'undefined') module.exports = { check };
if (!report.ok) process.exitCode = 1;
