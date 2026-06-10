import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {Scene} from '../types';
import {theme} from '../theme';
import {SceneShell} from './SceneShell';

const KEYWORDS = new Set([
  'import', 'from', 'def', 'class', 'return', 'if', 'else', 'elif', 'for',
  'while', 'in', 'not', 'and', 'or', 'with', 'as', 'try', 'except', 'raise',
  'lambda', 'None', 'True', 'False', 'print', 'async', 'await', 'const',
  'let', 'var', 'function', 'export', 'curl', 'cd', 'uv', 'pip', 'git', 'npx',
]);

/** 极简语法着色：注释 / 字符串 / 关键字 / 数字 */
const highlightLine = (line: string): React.ReactNode => {
  const commentIdx = (() => {
    const hash = line.indexOf('#');
    const slashes = line.indexOf('//');
    if (hash === -1) return slashes;
    if (slashes === -1) return hash;
    return Math.min(hash, slashes);
  })();

  let codePart = line;
  let commentPart = '';
  if (commentIdx >= 0) {
    codePart = line.slice(0, commentIdx);
    commentPart = line.slice(commentIdx);
  }

  const tokens = codePart.split(/("[^"]*"|'[^']*'|\s+|[()[\]{},.:=])/g);
  return (
    <>
      {tokens.map((tok, i) => {
        if (!tok) return null;
        if (/^["'].*["']$/.test(tok)) {
          return (
            <span key={i} style={{color: theme.orange}}>
              {tok}
            </span>
          );
        }
        if (KEYWORDS.has(tok)) {
          return (
            <span key={i} style={{color: theme.purple, fontWeight: 600}}>
              {tok}
            </span>
          );
        }
        if (/^\d+(\.\d+)?$/.test(tok)) {
          return (
            <span key={i} style={{color: theme.green}}>
              {tok}
            </span>
          );
        }
        return <span key={i}>{tok}</span>;
      })}
      {commentPart ? (
        <span style={{color: 'rgba(126, 226, 168, 0.75)', fontStyle: 'italic'}}>
          {commentPart}
        </span>
      ) : null}
    </>
  );
};

export const CodeScene: React.FC<{
  scene: Scene;
  footer: string;
}> = ({scene, footer}) => {
  const frame = useCurrentFrame();
  const lines = (scene.code ?? '').split('\n');

  const headingOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: 'clamp',
  });
  const panelOpacity = interpolate(frame, [10, 28], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // 代码行数较多时自动缩小字号
  const fontSize = lines.length > 18 ? 26 : lines.length > 12 ? 30 : 34;

  return (
    <SceneShell footer={footer}>
      <div style={{padding: '80px 120px 0'}}>
        <div style={{display: 'flex', alignItems: 'center', opacity: headingOpacity}}>
          <div
            style={{
              width: 14,
              height: 60,
              borderRadius: 7,
              background: `linear-gradient(180deg, ${theme.green}, ${theme.accent})`,
              marginRight: 32,
            }}
          />
          <h2 style={{fontSize: 60, margin: 0, fontWeight: 700}}>{scene.heading}</h2>
        </div>

        <div
          style={{
            marginTop: 50,
            background: 'rgba(6, 10, 26, 0.85)',
            border: `1.5px solid ${theme.panelBorder}`,
            borderRadius: 24,
            overflow: 'hidden',
            opacity: panelOpacity,
            boxShadow: '0 24px 80px rgba(0,0,0,0.45)',
          }}
        >
          {/* mac 风格窗口栏 */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '20px 28px',
              borderBottom: `1px solid ${theme.panelBorder}`,
            }}
          >
            {['#ff5f57', '#febc2e', '#28c840'].map((c) => (
              <div
                key={c}
                style={{width: 18, height: 18, borderRadius: '50%', background: c}}
              />
            ))}
            <span style={{marginLeft: 16, color: theme.textDim, fontSize: 24}}>
              {scene.codeLang ?? 'code'}
            </span>
          </div>
          <pre
            style={{
              margin: 0,
              padding: '36px 44px',
              fontFamily: theme.fontMono,
              fontSize,
              lineHeight: 1.65,
              color: theme.text,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            }}
          >
            {lines.map((line, i) => {
              const start = 20 + i * 4;
              const opacity = interpolate(frame, [start, start + 10], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });
              return (
                <div key={i} style={{opacity}}>
                  {highlightLine(line) ?? ' '}
                </div>
              );
            })}
          </pre>
        </div>
      </div>
    </SceneShell>
  );
};
