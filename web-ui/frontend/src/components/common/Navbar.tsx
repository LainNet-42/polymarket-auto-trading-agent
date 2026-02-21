import { useEffect, useState } from 'react';
import { fetchWallet } from '../../services/api';
import type { Page } from '../../App';
import './Navbar.css';

interface Props {
  currentPage: Page;
}

const Navbar = ({ currentPage }: Props) => {
  const [walletAddress, setWalletAddress] = useState('');

  useEffect(() => {
    fetchWallet().then((w) => setWalletAddress(w.address)).catch(() => {});
  }, []);

  const polygonscanUrl = walletAddress
    ? `https://polygonscan.com/address/${walletAddress}`
    : 'https://polygonscan.com';

  return (
    <nav className="navbar">
      <div className="navbar-container">
        <div className="navbar-logo">
          <a href="#/live" style={{ textDecoration: 'none' }}>
            <div className="logo-text">
              <span className="logo-alpha">Polymarket</span>
              <span className="logo-arena">Agent</span>
            </div>
          </a>
        </div>

        <ul className="navbar-menu-center">
          <li>
            <a
              href="#/live"
              className={currentPage === 'live' ? 'nav-active' : ''}
            >
              <span className="live-dot" />{' '}LIVE
            </a>
          </li>
          <li className="separator">|</li>
          <li>
            <a
              href="#/trading-log"
              className={currentPage === 'tradinglog' ? 'nav-active' : ''}
            >
              TRADING LOG
            </a>
          </li>
          <li className="separator">|</li>
          <li>
            <a
              href="#/trace"
              className={currentPage === 'trace' ? 'nav-active' : ''}
            >
              TRACE
            </a>
          </li>
        </ul>

        <div className="navbar-right">
          <a
            href={polygonscanUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="navbar-link"
          >
            WALLET
            <svg className="external-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path>
            </svg>
          </a>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
