import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Dispatch, PointerEvent, RefObject } from 'react';
import type { AppData } from '../lib/load';
import { buildLive } from '../lib/live';
import { CARD_LEVERS, leversMatchCard } from '../lib/scenario';
import type { Scenario } from '../lib/scenario';
import type { Action } from '../lib/state';
import { AccountPicker } from './AccountPicker';
import { BurnDown } from './BurnDown';
import { CustomerCard } from './CustomerCard';
import { JudgesPanel } from './JudgesPanel';
import { Levers } from './Levers';
import s from './Live.module.css';
import { Plans } from './Plans';
import { RealityPanel } from './RealityPanel';
import { TwistCards } from './TwistCards';

interface Props {
  data: AppData;
  scenario: Scenario;
  dispatch: Dispatch<Action>;
  searchRef: RefObject<HTMLInputElement | null>;
}

export function Live({ data, scenario, dispatch, searchRef }: Props) {
  const acct = data.byId.get(scenario.id);
  const model = useMemo(() => (acct ? buildLive(acct, scenario) : null), [acct, scenario]);
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

  if (!acct || !model) return null;

  return (
    <div className={s.live}>
      <div className={s.picker}>
        <AccountPicker ids={data.ids} has={has} current={acct.id} onOpen={open} inputRef={searchRef} />
      </div>
      <div className={s.cards}>
        <TwistCards
          card={scenario.card}
          matches={leversMatchCard(scenario.card, scenario.levers)}
          label={model.judgeShock.name}
          onPick={(card) => dispatch({ type: 'card', card })}
          onReset={() => dispatch({ type: 'reset' })}
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
          onReset={() => dispatch({ type: 'reset' })}
          cardLevers={CARD_LEVERS[scenario.card]}
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
