import { creditAdvice, isJobLoss, loanInTrouble, pyG } from '../engine';
import type { Account, GoalPlan, Ladder, Shock, Story } from '../engine';
import { money, rwText } from '../lib/format';
import s from './Plans.module.css';

interface Props {
  acct: Account;
  target: number;
  goal: GoalPlan;
  conventional: GoalPlan;
  ladder: Ladder;
  planShock: Shock;
  activeNames: string[];
  story: Story;
}

function FundCard({ goal, conventional, target }: { goal: GoalPlan; conventional: GoalPlan; target: number }) {
  const t = goal.targetBuffer;
  const share = t > 0 ? Math.max(0, Math.min(1, goal.currentBuffer / t)) : 1;
  const pctText = `${Math.floor(share * 100)}%`;
  return (
    <article className={s.card} aria-labelledby="fund-title">
      <p className={s.eyebrow}>Goal plan · normal times</p>
      <h3 id="fund-title" className={s.cardTitle}>
        Job-loss-proof fund ({target} months)
      </h3>
      <div className={s.big}>{money(t)}</div>
      <div className={s.progressLabel}>
        <span>
          Buffer now <strong>{money(goal.currentBuffer)}</strong>
        </span>
        <span>{goal.shortfall ? `${money(goal.shortfall)} to go` : 'already in place'}</span>
      </div>
      <div
        className={s.progress}
        role="progressbar"
        aria-label="Buffer as a share of the job-loss-proof fund"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.floor(share * 100)}
        aria-valuetext={`${pctText} of ${money(t)}`}
      >
        <div className={s.progressFill} style={{ width: `${share * 100}%` }} data-done={goal.shortfall === 0 ? 'true' : undefined} />
      </div>
      {goal.shortfall === 0 ? (
        <>
          <p className={s.text}>
            Keep it ring-fenced in a separate <strong>Tangerine Savings Account</strong> named <em>Emergency Fund</em>.
          </p>
          {goal.currentBuffer < goal.targetBuffer && (
            <p className={s.rounding}>
              Within rounding: {money(goal.targetBuffer - goal.currentBuffer)} under the exact target; the judges'
              runway rounds up to {target} months.
            </p>
          )}
        </>
      ) : goal.monthsToTarget ? (
        <p className={s.text}>
          Move the normal surplus of <strong>{money(goal.monthlySurplus)}/mo</strong> with the{' '}
          <strong>Automatic Savings Program</strong> into a <strong>Savings Goal</strong>: about{' '}
          <strong>{pyG(goal.monthsToTarget)} months</strong> to target.
        </p>
      ) : (
        <p className={s.text}>
          The normal-month surplus can't close the gap. Make the backup steps a permanent budget change and save the
          difference.
        </p>
      )}
      <p className={s.caption}>
        Conventional benchmark: 3 months of spending = {money(conventional.targetBuffer)}. The job-loss-proof target is
        exactly the buffer that passes this shock under the judges' formula.
      </p>
    </article>
  );
}

function LadderCard({ acct, ladder, planShock, target }: { acct: Account; ladder: Ladder; planShock: Shock; target: number }) {
  const stop = ladder.firstSufficient ?? ladder.rungs.length - 1;
  return (
    <article className={s.card} aria-labelledby="ladder-title">
      <p className={s.eyebrow}>Backup plan · if the shock hits</p>
      <h3 id="ladder-title" className={s.cardTitle}>
        {loanInTrouble(acct)
          ? ladder.verdict.replace('income or credit', 'income or a hardship deferral').replace('cash or credit', 'cash or a hardship deferral')
          : ladder.verdict}
      </h3>
      <p className={s.caption}>
        Under the shock: {rwText(ladder.shocked)}. Steps add up, cheapest first, and stop at the first one that reaches{' '}
        {target} months.
      </p>
      {ladder.rungs.length > 0 && (
        <ol className={s.ladder}>
          {ladder.rungs.map((r, i) => {
            const state = i <= stop ? (r.reachesTarget ? 'hit' : 'lit') : 'off';
            return (
              <li key={r.step} className={s.rung} data-state={state}>
                <span className={s.rungDot} aria-hidden="true">
                  {state === 'hit' ? '✓' : i + 1}
                </span>
                <span className={s.rungStep}>
                  {r.step}
                  <span className={s.rungMeta}>
                    saves {money(r.monthlySaving)}/mo · runway {rwText(r.result)}
                    {state === 'hit' && ` · reaches ${target} mo`}
                    {state === 'off' && ' · not needed'}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {ladder.cashOrCreditNeeded > 0 && (
        <p className={s.credit} data-trouble={loanInTrouble(acct) ? 'true' : undefined}>
          {creditAdvice(acct, ladder.cashOrCreditNeeded, isJobLoss(planShock))}
        </p>
      )}
    </article>
  );
}

function StoryCard({ story }: { story: Story }) {
  return (
    <article className={`${s.card} ${s.story}`} aria-labelledby="story-title">
      <p className={s.eyebrow}>The story · template, offline</p>
      <h3 id="story-title" className={s.storyHead}>
        {story.headline}
      </h3>
      <p className={s.text}>{story.what_changed}</p>
      <ul className={s.steps}>
        {story.plan_steps.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
      <p className={s.caption}>
        Reality check: {story.reality_check}. {story.caveat}
      </p>
    </article>
  );
}

export function Plans({ acct, target, goal, conventional, ladder, planShock, activeNames, story }: Props) {
  return (
    <section className={s.panel} aria-labelledby="plans-title">
      <div className={s.head}>
        <h2 id="plans-title" className={s.headTitle}>
          Make a plan
        </h2>
        <span className={s.basis}>
          Plans use the judges' numbers{activeNames.length ? ` plus your reality checks: ${activeNames.join(', ')}.` : '.'}
        </span>
      </div>
      <div className={s.grid}>
        <FundCard goal={goal} conventional={conventional} target={target} />
        <LadderCard acct={acct} ladder={ladder} planShock={planShock} target={target} />
        <StoryCard story={story} />
      </div>
    </section>
  );
}
