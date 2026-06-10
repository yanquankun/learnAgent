---
title: 浏览器事件循环机制：宏任务与微任务详解
slug: browser-event-loop
tags: [javascript, browser, frontend]
createdAt: 2025-07-18
---

## JavaScript 为什么是单线程

JavaScript 设计为单线程是因为它要操作 DOM：如果两个线程同时修改同一个
DOM 节点，浏览器无法决定以谁为准。单线程意味着同一时刻只能做一件事，
耗时操作会阻塞页面，所以浏览器引入了事件循环来调度异步任务。

## 宏任务与微任务

异步任务分为两类。宏任务包括 setTimeout、setInterval、I/O、用户交互事件。
微任务包括 Promise.then、queueMicrotask、MutationObserver。

事件循环的执行顺序是：执行一个宏任务，然后清空整个微任务队列，
然后进行渲染（如果需要），再取下一个宏任务。
记住关键点：微任务永远比下一个宏任务先执行。

## 经典面试题解析

console.log 同步代码先执行，Promise.then 作为微任务紧随其后，
setTimeout 即使延时为 0 也要等到下一轮宏任务。
所以输出顺序永远是：同步代码、微任务、宏任务。

## 实战意义

理解事件循环不只是为了面试。比如 Vue 的 nextTick 利用微任务在 DOM
更新后执行回调；React 的调度器用 MessageChannel 宏任务实现时间切片；
长任务拆分要用 setTimeout 而不是 Promise，否则微任务队列永远清不空，
页面照样卡死。
