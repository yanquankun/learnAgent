import React from 'react';
import {AbsoluteFill} from 'remotion';
import {theme} from '../theme';

/**
 * 所有场景的公共外壳：背景 + 装饰光斑 + 底部页脚。
 */
export const SceneShell: React.FC<{
  footer?: string;
  children: React.ReactNode;
}> = ({footer, children}) => {
  return (
    <AbsoluteFill
      style={{
        background: theme.bg,
        fontFamily: theme.fontSans,
        color: theme.text,
        overflow: 'hidden',
      }}
    >
      {/* 装饰光斑 */}
      <div
        style={{
          position: 'absolute',
          width: 900,
          height: 900,
          borderRadius: '50%',
          background:
            'radial-gradient(circle, rgba(91,155,255,0.16) 0%, rgba(91,155,255,0) 70%)',
          top: -350,
          right: -250,
        }}
      />
      <div
        style={{
          position: 'absolute',
          width: 700,
          height: 700,
          borderRadius: '50%',
          background:
            'radial-gradient(circle, rgba(196,166,255,0.10) 0%, rgba(196,166,255,0) 70%)',
          bottom: -300,
          left: -200,
        }}
      />
      {children}
      {footer ? (
        <div
          style={{
            position: 'absolute',
            bottom: 36,
            left: 80,
            right: 80,
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 26,
            color: theme.textDim,
            letterSpacing: 1,
          }}
        >
          <span>{footer}</span>
          <span>learnAgent 教学课程</span>
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
