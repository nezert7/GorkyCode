import React from 'react';
import { HeaderTitle } from '../components/HeaderTitle.tsx';

interface StartScreenProps {
  onStart: () => void;
}

export const StartScreen: React.FC<StartScreenProps> = ({ onStart }) => {
  return (
    <div className="screen start-screen">
      <div className="left-content">
        <HeaderTitle />

        <div className="action-group">
          <button className="pixel-btn-start" onClick={onStart}>
            START
          </button>
          <p className="subtext">Я всё помню . . .</p>
        </div>
      </div>

      <div className="character-container">
        <img src="/crow-start.png" alt="Vorona Start" className="pixel-art" />
      </div>
    </div>
  );
};