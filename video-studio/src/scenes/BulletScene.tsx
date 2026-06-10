import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {Scene, sceneDuration} from '../types';
import {theme} from '../theme';
import {SceneShell} from './SceneShell';

export const BulletScene: React.FC<{
  scene: Scene;
  footer: string;
}> = ({scene, footer}) => {
  const frame = useCurrentFrame();
  const duration = sceneDuration(scene);
  const bullets = scene.bullets ?? [];

  const headingOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: 'clamp',
  });

  // 要点在场景前 60% 的时间内依次出现，与解说节奏大致同步
  const revealSpan = duration * 0.6;
  const startOf = (i: number) =>
    bullets.length > 1 ? (revealSpan * i) / bullets.length : 0;

  return (
    <SceneShell footer={footer}>
      <div style={{padding: '90px 120px 0'}}>
        <div style={{display: 'flex', alignItems: 'center', opacity: headingOpacity}}>
          <div
            style={{
              width: 14,
              height: 64,
              borderRadius: 7,
              background: `linear-gradient(180deg, ${theme.accent}, ${theme.purple})`,
              marginRight: 32,
            }}
          />
          <h2 style={{fontSize: 64, margin: 0, fontWeight: 700}}>{scene.heading}</h2>
        </div>

        <div style={{marginTop: 70, display: 'flex', flexDirection: 'column', gap: 42}}>
          {bullets.map((b, i) => {
            const start = startOf(i);
            const opacity = interpolate(frame, [start, start + 18], [0, 1], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
            const translateX = interpolate(frame, [start, start + 18], [40, 0], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
            });
            return (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  opacity,
                  transform: `translateX(${translateX}px)`,
                  background: theme.panel,
                  border: `1.5px solid ${theme.panelBorder}`,
                  borderRadius: 20,
                  padding: '30px 40px',
                }}
              >
                <div
                  style={{
                    minWidth: 52,
                    height: 52,
                    borderRadius: 14,
                    background: theme.accentSoft,
                    color: theme.accent,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 30,
                    fontWeight: 700,
                    marginRight: 34,
                  }}
                >
                  {i + 1}
                </div>
                <p
                  style={{
                    fontSize: 38,
                    lineHeight: 1.6,
                    margin: 0,
                    color: theme.text,
                  }}
                >
                  {b}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </SceneShell>
  );
};
