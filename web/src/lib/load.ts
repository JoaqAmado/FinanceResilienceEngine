/**
 * Data loading. accounts.json and portfolio.json are fetched once (started from main.tsx before
 * React renders); each account's month history is fetched only when that account is opened.
 */
import { useEffect, useState } from 'react';
import { decodeAccounts, decodeBacktest } from '../engine';
import type { Account, AccountHistory, AccountsFile, Backtest, PortfolioFile } from '../engine';

const BASE = import.meta.env.BASE_URL;

export interface AppData {
  accounts: Account[];
  byId: Map<number, Account>;
  /** every account_id, ascending */
  ids: number[];
  portfolio: PortfolioFile;
  /** the early-warning light's backtest tiers (portfolio.json early_warning) */
  earlyWarning: Backtest;
  /** time from first request to decoded data, ms */
  loadMs: number;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

let appData: Promise<AppData> | null = null;

export function loadAppData(): Promise<AppData> {
  if (!appData) {
    const t0 = performance.now();
    appData = Promise.all([
      getJson<AccountsFile>('data/accounts.json'),
      getJson<PortfolioFile>('data/portfolio.json'),
    ]).then(([file, portfolio]) => {
      const accounts = decodeAccounts(file);
      const byId = new Map(accounts.map((a) => [a.id, a] as const));
      const ids = accounts.map((a) => a.id).sort((a, b) => a - b);
      const earlyWarning = decodeBacktest(portfolio.early_warning);
      return { accounts, byId, ids, portfolio, earlyWarning, loadMs: performance.now() - t0 };
    });
  }
  return appData;
}

export function useAppData(): { data: AppData | null; error: string | null } {
  const [state, setState] = useState<{ data: AppData | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let alive = true;
    loadAppData().then(
      (data) => alive && setState({ data, error: null }),
      (e: unknown) => alive && setState({ data: null, error: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      alive = false;
    };
  }, []);
  return state;
}

const histories = new Map<number, Promise<AccountHistory>>();

export function loadHistory(id: number): Promise<AccountHistory> {
  let p = histories.get(id);
  if (!p) {
    p = getJson<AccountHistory>(`data/history/${id}.json`);
    p.catch(() => histories.delete(id)); // let a later open retry
    histories.set(id, p);
  }
  return p;
}

export function useHistory(id: number): { history: AccountHistory | null; error: string | null } {
  const [state, setState] = useState<{ id: number; history: AccountHistory | null; error: string | null }>({
    id,
    history: null,
    error: null,
  });
  useEffect(() => {
    let alive = true;
    loadHistory(id).then(
      (history) => alive && setState({ id, history, error: null }),
      (e: unknown) => alive && setState({ id, history: null, error: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      alive = false;
    };
  }, [id]);
  return state.id === id ? state : { history: null, error: null };
}
