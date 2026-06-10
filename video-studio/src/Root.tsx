import React from 'react';
import {CalculateMetadataFunction, Composition} from 'remotion';
import {ChapterVideo} from './ChapterVideo';
import {ChapterData, FPS, totalDuration} from './types';

/** Studio 预览用的示例数据；实际渲染时由 --props 传入 pipeline 生成的 scenes.json */
const demoData: ChapterData = {
  slug: 'demo',
  courseTitle: 'learnAgent',
  moduleTitle: '01-LLM基础',
  chapterTitle: '（一）认识 LLM 与第一次 API 调用',
  scenes: [
    {
      type: 'title',
      heading: '认识 LLM 与第一次 API 调用',
      bullets: ['完成人生第一次「用代码调用大模型」'],
      narration: '欢迎来到课程第一章。',
      durationInFrames: 150,
    },
    {
      type: 'bullets',
      heading: 'LLM 到底在做什么？',
      bullets: [
        '根据已有文字，预测下一个最可能出现的 token',
        '上下文窗口决定模型一次能看到多少内容',
        '补全机制解释了为什么 Prompt 写法影响巨大',
      ],
      narration: 'LLM 的本质是预测下一个 token。',
      durationInFrames: 240,
    },
    {
      type: 'code',
      heading: '第一次 API 调用',
      code: 'messages = [\n    {"role": "system", "content": "你是一位资深编程导师"},\n    {"role": "user", "content": "什么是LLM？"},\n]\nresponse = client.chat.completions.create(\n    model="deepseek-chat",\n    messages=messages,\n)  # 返回 ChatCompletion 对象',
      codeLang: 'python',
      narration: '我们用 OpenAI SDK 调用 DeepSeek。',
      durationInFrames: 240,
    },
    {
      type: 'outro',
      heading: '本章小结',
      bullets: ['你已经能让模型「说话」了', '下一章：Prompt 工程基础'],
      narration: '下一章见。',
      durationInFrames: 150,
    },
  ],
};

const calculateMetadata: CalculateMetadataFunction<ChapterData> = ({props}) => ({
  durationInFrames: totalDuration(props),
});

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="ChapterVideo"
      component={ChapterVideo}
      width={1920}
      height={1080}
      fps={FPS}
      defaultProps={demoData}
      calculateMetadata={calculateMetadata}
    />
  );
};
