import React from 'react';
import { HeaderTitle } from '../components/HeaderTitle.tsx';

export const MainScreen: React.FC = () => {
  return (
    <div className="screen main-screen">
      <div className="left-content">
        <HeaderTitle />

        <div className="main-controls">
          <div className="icon-action-wrapper">
            <span className="arrow">➔</span>
            <button className="pixel-icon-btn">
              <img src="/headphones.png" alt="Listen" className="pixel-art-icon" />
            </button>
            <span className="arrow">⬅</span>
          </div>

          <p className="status-text">слушаю и напоминаю</p>
          <a href="#history" className="history-link">история запросов</a>
        </div>
      </div>

      <div className="character-container">
        <img src="/crow-full.png" alt="Vorona Main" className="pixel-art" />
      </div>
    </div>
  );
};