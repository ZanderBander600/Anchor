export interface SubNavItem {
  id: string;
  label: string;
}

export interface SubNavProps {
  items: SubNavItem[];
  active: string;
  onSelect: (id: string) => void;
  /** Accessible name for the tablist, e.g. "Underwrite sections". */
  label: string;
  /** `segmented` is the pill-style control used for a workspace's primary
   * internal navigation; `inline` is the lighter underlined style used one
   * level deeper, so two nested navs never look like peers. */
  variant?: 'segmented' | 'inline';
  /** Optional id wiring so each tab can point at the panel it controls. */
  idFor?: (id: string) => string;
  controlsFor?: (id: string) => string;
}

/**
 * Sprint C Gate C3 -- reusable internal navigation for a workspace.
 *
 * The ARIA tabs pattern, one level below `WorkspaceNav`. Purely
 * presentational: it owns no state and performs no calculation. Callers keep
 * the selected id in their own state, so switching sections never remounts
 * or resets anything the section contains.
 */
export function SubNav({
  items,
  active,
  onSelect,
  label,
  variant = 'segmented',
  idFor,
  controlsFor,
}: SubNavProps) {
  return (
    <div className={`sub-nav sub-nav-${variant}`} role="tablist" aria-label={label}>
      {items.map((item) => {
        const isActive = item.id === active;
        return (
          <button
            key={item.id}
            id={idFor?.(item.id)}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-controls={controlsFor?.(item.id)}
            className={isActive ? 'sub-nav-item sub-nav-item-active' : 'sub-nav-item'}
            onClick={() => onSelect(item.id)}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
