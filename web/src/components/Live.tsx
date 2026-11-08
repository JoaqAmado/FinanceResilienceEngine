import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Dispatch, PointerEvent, RefObject } from 'react';
import { accountFlags, balancePath } from '../engine';
import { checkView, verdictKind } from '../engine/consistency';
import type { Issue } from '../engine/consistency';
import { describeShock } from '../engine/shock_parser';
import type { AccountIndex } from '../engine/shock_parser';
import { send } from '../lib/chat';
import type { ChatState } from '../lib/chat';
import { rwText } from '../lib/format';
import type { AppData } from '../lib/load';
import { buildLive } from '../lib/live';
import type { LiveModel } from '../lib/live';
import { burnDownHorizon } from '../lib/paths';
import type { Scenario } from '../lib/scenario';
import type { Action } from '../lib/state';
import { AccountPicker } from './AccountPicker';
import { BurnDown } from './BurnDown';
import { ChatPanel } from './ChatPanel';
import { CustomerCard } from './CustomerCard';
import { JudgesPanel } from './JudgesPanel';
import { Levers } from './Levers';
import s from './Live.module.css';
import { Plans } from './Plans';
import { RealityPanel } from './RealityPanel';

interface Props {
  data: AppData;
  scenario: Scenario;
  dispatch: Dispatch<Action>;
  searchRef: RefObject<HTMLInputElement | null>;
  chat: ChatState;
  setChat: (c: ChatState) => void;
  chatRef?: RefObject<HTMLInputElement | null>;
}

export function accountIndex(data: AppData): AccountIndex {
  return { get: (id) => data.byId.get(id), minId: Math.min(...data.ids), maxId: Math.max(...data.ids) };
}

/** resilience/consistency.check_view on what this screen shows. */
export function screenIssues(acct: AppData['accounts'][number], scenario: Scenario, model: LiveModel,
  chat: ChatState): Issue[] {
  return checkView(acct, model.realShock, scenario.target, {
    accountId: acct.id,
    levers: scenario.levers,
    toggles: scenario.toggles,
    chat: chat.last,
    understoodAs: describeShock(model.realShock, acct, scenario.target),
    twistLabel: model.judgeShock.name,
    card: { I: acct.I, F: acct.F, S: acct.S, B: acct.B, H: acct.H, P: acct.P, Pn: acct.Pn },
    judgeShock: model.judgeShock,
    judge: model.judge,
    judgeText: rwText(model.judge),
    verdict: verdictKind(acct, model.judge, scenario.target),
    judgePath: balancePath(acct, model.judgeShock, burnDownHorizon(model.judge)),
    jan: model.jan,
    real: model.real,
    checks: model.checks,
    ladder: model.ladder,
    goal: model.goal,
    goalShock: model.goalShock,
    story: model.story,
    facts: model.facts,
    flags: accountFlags(acct).map(([code]) => code),
  });
}

export function Live({ data, scenario, dispatch, searchRef, chat, setChat, chatRef }: Props) {
  const acct = data.byId.get(scenario.id);
  const model = useMemo(() => (acct ? buildLive(acct, scenario) : null), [acct, scenario]);
  const issues = useMemo(() => (acct && model ? screenIssues(acct, scenario, model, chat) : []),
    [acct, scenario, model, chat]);
  const index = useMemo(() => accountIndex(data), [data]);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const up = () => setDragging(false);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
  }, []);

  const onLeversPointer = useCallback((e: PointerEvent<HTMLDivElement>) => {
    if (e.target instanceof HTMLInputElement && e.target.type === 'range') setDragging(true);
  }, []);

  const has = useCallback((id: number) => data.byId.has(id), [data]);
  const open = useCallback((id: number) => dispatch({ type: 'open', id }), [dispatch]);
  const onSend = useCallback((text: string) => {
    if (!acct) return;
    const out = send(text, scenario, acct, index, chat);
    setChat(out.chat);
    if (out.action) dispatch(out.action);
  }, [acct, scenario, index, chat, setChat, dispatch]);

  if (!acct || !model) return null;

  return (
    <div className={s.live}>
      <div className={s.picker}>
        <AccountPicker ids={data.ids} has={has} current={acct.id} onOpen={open} inputRef={searchRef} />
      </div>
      <div className={s.cards}>
        <ChatPanel
          chat={chat}
          understoodAs={describeShock(model.realShock, acct, scenario.target)}
          issues={issues}
          onSend={onSend}
          inputRef={chatRef}
        />
      </div>
      <div className={s.customer}>
        <CustomerCard acct={acct} baseline={model.baseline} earlyWarning={data.earlyWarning} />
      </div>
      <div className={s.judges}>
        <JudgesPanel
          acct={acct}
          judge={model.judge}
          baseline={model.baseline}
          shock={model.judgeShock}
          target={scenario.target}
          greyNote={model.greyNote}
          dragging={dragging}
        />
      </div>
      <div className={s.reality}>
        <RealityPanel
          judge={model.judge}
          real={model.real}
          dragging={dragging}
          anyOn={model.anyCheckOn}
          activeNames={model.activeNames}
          checks={model.checks}
          jan={model.jan}
          onToggle={(key, on) => dispatch({ type: 'toggle', key, on })}
        />
      </div>
      <div className={s.levers} onPointerDown={onLeversPointer}>
        <Levers
          levers={scenario.levers}
          target={scenario.target}
          onLevers={(patch) => dispatch({ type: 'levers', patch })}
          onTarget={(n) => dispatch({ type: 'target', n })}
          onReset={() => onSend('reset')}
          chatLevers={chat.last?.accountId === acct.id ? chat.last.levers : undefined}
          chatTarget={chat.last?.accountId === acct.id ? chat.last.target : undefined}
        />
      </div>
      <div className={s.chart}>
        <BurnDown
          acct={acct}
          judgeShock={model.judgeShock}
          judge={model.judge}
          planShock={model.planShock}
          ladder={model.ladder}
          target={scenario.target}
          activeNames={model.activeNames}
          dragging={dragging}
        />
      </div>
      <div className={s.plans}>
        <Plans
          acct={acct}
          target={scenario.target}
          goal={model.goal}
          conventional={model.conventional}
          ladder={model.ladder}
          planShock={model.planShock}
          activeNames={model.activeNames}
          story={model.story}
        />
      </div>
    </div>
  );
}
