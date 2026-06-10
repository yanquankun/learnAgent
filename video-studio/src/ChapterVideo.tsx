import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {ChapterData, Scene, sceneDuration, totalDuration} from './types';
import {theme} from './theme';
import {TitleScene} from './scenes/TitleScene';
import {BulletScene} from './scenes/BulletScene';
import {CodeScene} from './scenes/CodeScene';
import {OutroScene} from './scenes/OutroScene';

const FADE = 10;

/** 每个场景统一做淡入淡出，衔接更柔和 */
const SceneFade: React.FC<{duration: number; children: React.ReactNode}> = ({
  duration,
  children,
}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [0, FADE, Math.max(FADE + 1, duration - FADE), duration],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  return <AbsoluteFill style={{opacity}}>{children}</AbsoluteFill>;
};

const renderScene = (scene: Scene, data: ChapterData) => {
  const footer = `${data.moduleTitle} · ${data.chapterTitle}`;
  switch (scene.type) {
    case 'title':
      return (
        <TitleScene
          scene={scene}
          moduleTitle={data.moduleTitle}
          chapterTitle={data.chapterTitle}
        />
      );
    case 'code':
      return <CodeScene scene={scene} footer={footer} />;
    case 'outro':
      return <OutroScene scene={scene} footer={footer} />;
    default:
      return <BulletScene scene={scene} footer={footer} />;
  }
};

const ProgressBar: React.FC<{total: number}> = ({total}) => {
  const frame = useCurrentFrame();
  const progress = Math.min(1, frame / Math.max(1, total));
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        height: 10,
        width: `${progress * 100}%`,
        background: `linear-gradient(90deg, ${theme.accent}, ${theme.purple})`,
        zIndex: 10,
      }}
    />
  );
};

export const ChapterVideo: React.FC<ChapterData> = (data) => {
  const total = totalDuration(data);
  let from = 0;

  return (
    <AbsoluteFill style={{background: '#0b1026'}}>
      {data.scenes.map((scene, i) => {
        const duration = sceneDuration(scene);
        const start = from;
        from += duration;
        return (
          <Sequence key={i} from={start} durationInFrames={duration}>
            {scene.audioFile ? <Audio src={staticFile(scene.audioFile)} /> : null}
            <SceneFade duration={duration}>{renderScene(scene, data)}</SceneFade>
          </Sequence>
        );
      })}
      <ProgressBar total={total} />
    </AbsoluteFill>
  );
};
