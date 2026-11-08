import { CARDS } from '../lib/scenario';
import type { CardId } from '../lib/scenario';
import s from './TwistCards.module.css';

interface Props {
  card: CardId;
  /** the levers still equal the selected card */
  matches: boolean;
  label: string;
  onPick: (card: CardId) => void;
  onReset: () => void;
}

export function TwistCards({ card, matches, label, onPick, onReset }: Props) {
  return (
    <div className={s.wrap}>
      <div className={s.cards} role="group" aria-label="Twist card (keys 1 to 4)">
        {CARDS.map((c) => (
          <button
            key={c.id}
            type="button"
            className={s.card}
            aria-pressed={card === c.id}
            aria-keyshortcuts={c.key}
            onClick={() => onPick(c.id)}
          >
            <span className={s.key} aria-hidden="true">
              {c.key}
            </span>
            <span className={s.title}>{c.title}</span>
            <span className={s.detail}>{c.detail}</span>
          </button>
        ))}
      </div>
      <div className={s.status} aria-live="polite">
        <span className={s.applied}>
          Applied: <strong>{label}</strong>
        </span>
        {!matches && card !== 'custom' && <span className={s.edited}>levers changed from the card</span>}
        <button type="button" className={s.reset} onClick={onReset} aria-keyshortcuts="r">
          ↺ Reset card
        </button>
      </div>
    </div>
  );
}
