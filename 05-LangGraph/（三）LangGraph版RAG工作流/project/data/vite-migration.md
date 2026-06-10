---
title: webpack 迁移 Vite 实录：冷启动从12秒到0.8秒
slug: vite-migration
tags: [vite, webpack, engineering]
createdAt: 2025-09-03
---

## 迁移背景

我的博客项目用 webpack 构建已经三年，随着页面和依赖越来越多，
开发服务器冷启动需要 12 秒，热更新也要 2 到 3 秒，开发体验越来越差。
Vite 利用浏览器原生 ES Module 实现按需编译，开发环境几乎不需要打包，
这是它快的根本原因。

## 三个迁移大坑

### 坑一：CommonJS 依赖处理

老项目里有不少 require 写法的依赖包，Vite 的开发模式只认 ES Module。
解决方法是依靠 Vite 的依赖预构建（pre-bundling），它会用 esbuild 把
CommonJS 依赖转换成 ESM。少数顽固的包需要手动加入 optimizeDeps.include。

### 坑二：环境变量的写法变化

webpack 项目里习惯用 process.env.NODE_ENV，Vite 中要改成 import.meta.env，
并且自定义环境变量必须以 VITE_ 为前缀才会暴露给客户端代码。
这是为了防止服务端的敏感环境变量意外泄漏到浏览器。

### 坑三：生产构建的分包配置

Vite 生产构建用的是 Rollup。默认分包策略对大项目不够友好，
需要在 build.rollupOptions.output.manualChunks 里手动把
node_modules 的依赖拆分成独立的 vendor 包，提升缓存命中率。

## 迁移效果

冷启动时间从 12 秒降到 0.8 秒，热更新从秒级变成毫秒级几乎无感，
生产构建时间从 96 秒降到 31 秒。对中小型项目，强烈建议尽早迁移。
