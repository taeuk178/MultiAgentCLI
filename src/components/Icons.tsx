type IconProps = { size?: number };

export const IconSidebar = ({ size = 14 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <rect x="2" y="3" width="12" height="10" rx="1.8" stroke="currentColor" strokeWidth="1.2" />
    <line x1="6.5" y1="3.5" x2="6.5" y2="12.5" stroke="currentColor" strokeWidth="1.2" />
  </svg>
);

export const IconPlus = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M8 3.5v9M3.5 8h9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

export const IconRefresh = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M13 8a5 5 0 1 1-1.5-3.6L13 6M13 3v3h-3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IconSend = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M2.5 8L13.5 3 11 13.5 8 9 2.5 8z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
  </svg>
);

export const IconStop = ({ size = 12 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor">
    <rect x="4" y="4" width="8" height="8" rx="1.5" />
  </svg>
);

export const IconTerminal = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <rect x="2" y="3" width="12" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
    <path d="M5 6.5l2 1.5-2 1.5M8.5 10h2.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IconFolder = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M2.5 5.5a1 1 0 0 1 1-1H7l1.5 1.5h4a1 1 0 0 1 1 1V12a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1V5.5z" stroke="currentColor" strokeWidth="1.2" />
  </svg>
);

export const IconTrash = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M3.5 5h9M6.5 5V3.5h3V5M5 5l.5 8.5h5L11 5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IconLink = ({ size = 11 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M7 9.5a2.5 2.5 0 0 0 3.5 0l2-2a2.5 2.5 0 0 0-3.5-3.5L8 5M9 6.5a2.5 2.5 0 0 0-3.5 0l-2 2a2.5 2.5 0 0 0 3.5 3.5L8 11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

export const IconLogin = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.2" />
    <path d="M5.5 8.5L7.2 10l3.3-3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IconLogout = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.2" />
    <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
  </svg>
);

export const IconX = ({ size = 12 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

export const IconChev = ({ size = 10 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IconChevDown = ({ size = 10 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IconAttach = ({ size = 13 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M11 5L6 10a2 2 0 0 0 2.8 2.8l5-5a3.5 3.5 0 0 0-5-5l-5 5a5 5 0 0 0 7 7L11 13" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const IconCheck = ({ size = 12 }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
    <path d="M3 8l3 3 7-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
