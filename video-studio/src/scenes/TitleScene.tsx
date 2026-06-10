import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {Scene} from '../types';
import {theme} from '../theme';
import {SceneShell} from './SceneShell';

export const TitleScene: React.FC<{
  scene: Scene;
  moduleTitle: string;
  chapterTitle: string;
}> = ({scene, moduleTitle}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const badgeOpacity = interpolate(frame, [0, 18], [0, 1], {
    extrapolateRight: 'clamp',
  });
  const titleScale = spring({frame: frame - 8, fps, config: {damping: 200}});
  const titleOpacity = interpolate(frame, [8, 30], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const lineWidth = interpolate(frame, [25, 55], [0, 280], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const subOpacity = interpolate(frame, [40, 65], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <SceneShell>
      <AbsoluteFill
        style={{
          justifyContent: 'center',
          alignItems: 'center',
          textAlign: 'center',
          padding: '0 140px',
        }}
      >
        <div
          style={{
            opacity: badgeOpacity,
            background: theme.accentSoft,
            border: `2px solid ${theme.accent}`,
            color: theme.text,
            borderRadius: 999,
            padding: '12px 38px',
            fontSize: 32,
            letterSpacing: 2,
            marginBottom: 56,
          }}
        >
          {moduleTitle}
        </div>
        <h1
          style={{
            fontSize: 92,
            lineHeight: 1.25,
            margin: 0,
            fontWeight: 700,
            transform: `scale(${0.92 + titleScale * 0.08})`,
            opacity: titleOpacity,
          }}
        >
          {scene.heading}
        </h1>
        <div
          style={{
            width: lineWidth,
            height: 8,
            borderRadius: 4,
            background: `linear-gradient(90deg, ${theme.accent}, ${theme.purple})`,
            margin: '48px 0',
          }}
        />
        {scene.bullets?.length ? (
          <p
            style={{
              fontSize: 38,
              color: theme.textDim,
              margin: 0,
              maxWidth: 1280,
              lineHeight: 1.7,
              opacity: subOpacity,
            }}
          >
            {scene.bullets[0]}
          </p>
        ) : null}
      </AbsoluteFill>
    </SceneShell>
  );
};
