import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {Scene} from '../types';
import {theme} from '../theme';
import {SceneShell} from './SceneShell';

export const OutroScene: React.FC<{
  scene: Scene;
  footer: string;
}> = ({scene, footer}) => {
  const frame = useCurrentFrame();
  const bullets = scene.bullets ?? [];

  const headingOpacity = interpolate(frame, [0, 18], [0, 1], {
    extrapolateRight: 'clamp',
  });

  return (
    <SceneShell footer={footer}>
      <AbsoluteFill
        style={{
          justifyContent: 'center',
          alignItems: 'center',
          textAlign: 'center',
          padding: '0 160px',
        }}
      >
        <h2
          style={{
            fontSize: 76,
            margin: 0,
            fontWeight: 700,
            opacity: headingOpacity,
          }}
        >
          {scene.heading}
        </h2>
        <div
          style={{
            width: 220,
            height: 8,
            borderRadius: 4,
            background: `linear-gradient(90deg, ${theme.orange}, ${theme.accent})`,
            margin: '52px 0 64px',
          }}
        />
        <div style={{display: 'flex', flexDirection: 'column', gap: 36, maxWidth: 1400}}>
          {bullets.map((b, i) => {
            const start = 20 + i * 14;
            const opacity = interpolate(frame, [start, start + 16], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
            return (
              <p
                key={i}
                style={{
                  fontSize: 42,
                  lineHeight: 1.7,
                  margin: 0,
                  color: theme.textDim,
                  opacity,
                }}
              >
                {b}
              </p>
            );
          })}
        </div>
      </AbsoluteFill>
    </SceneShell>
  );
};
