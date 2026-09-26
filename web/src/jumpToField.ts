/**
 * Move the analyst to a named control elsewhere in the same editor: scroll it
 * into view and give it focus, so keyboard and pointer users arrive at the
 * same place. Used where two linked records are edited in different parts of
 * one form -- a refinance and the replacement loan it funds -- so neither has
 * to be found by scrolling.
 *
 * Presentation only: it moves focus and changes no value.
 */
export function jumpToField(id: string): void {
  const target = document.getElementById(id);
  if (target === null) {
    return;
  }
  if (typeof target.scrollIntoView === 'function') {
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  target.focus({ preventScroll: true });
}
