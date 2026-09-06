/** Minimal stroke/fill SVG icon set (no emoji anywhere in the UI). */

function base(props: React.SVGProps<SVGSVGElement>, children: React.ReactNode) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="currentColor"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export const IPlay = (p: React.SVGProps<SVGSVGElement>) =>
  base(p, <path d="M8 5v14l11-7z" />);

export const IPause = (p: React.SVGProps<SVGSVGElement>) =>
  base(p, <path d="M6 5h4v14H6zM14 5h4v14h-4z" />);

export const IPlus = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z" />
  );

export const ICheck = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z" />
  );

export const IClose = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z" />
  );

export const IChevL = (p: React.SVGProps<SVGSVGElement>) =>
  base(p, <path d="M15.4 7.4 14 6l-6 6 6 6 1.4-1.4L10.8 12z" />);

export const IChevR = (p: React.SVGProps<SVGSVGElement>) =>
  base(p, <path d="M8.6 16.6 10 18l6-6-6-6-1.4 1.4 4.6 4.6z" />);

export const IBack = (p: React.SVGProps<SVGSVGElement>) =>
  base(p, <path d="M20 11H7.8l5.6-5.6L12 4l-8 8 8 8 1.4-1.4L7.8 13H20z" />);

export const IRew10 = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <>
      <path d="M12 5V1L7 6l5 5V7c3.3 0 6 2.7 6 6s-2.7 6-6 6-6-2.7-6-6H4c0 4.4 3.6 8 8 8s8-3.6 8-8-3.6-8-8-8z" />
      <text x="11" y="17.5" fontSize="7" fontWeight="700" textAnchor="middle">10</text>
    </>
  );

export const IFwd10 = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <>
      <path d="M12 5V1l5 5-5 5V7c-3.3 0-6 2.7-6 6s2.7 6 6 6 6-2.7 6-6h2c0 4.4-3.6 8-8 8s-8-3.6-8-8 3.6-8 8-8z" />
      <text x="13" y="17.5" fontSize="7" fontWeight="700" textAnchor="middle">10</text>
    </>
  );

export const IVol = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4zM14 3.2v2.1a7 7 0 0 1 0 13.4v2.1a9 9 0 0 0 0-17.6z" />
  );

export const IMute = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M16.5 12A4.5 4.5 0 0 0 14 8v2.2l2.4 2.4c.06-.2.1-.4.1-.6zm2.5 0c0 .94-.2 1.82-.54 2.64l1.5 1.5A8.8 8.8 0 0 0 21 12a9 9 0 0 0-7-8.77v2.06A7 7 0 0 1 19 12zM4.3 3 3 4.3 7.7 9H3v6h4l5 5v-6.7l5.3 5.3 1.4-1.4L4.3 3zM12 4 9.9 6.1 12 8.2V4z" />
  );

export const IFull = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z" />
  );

export const IInfo = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z" />
  );

export const IRefresh = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M17.7 6.3A8 8 0 1 0 19.7 14h-2.1A6 6 0 1 1 12 6c1.5 0 2.9.6 4 1.5L13 10h7V3l-2.3 3.3z" />
  );

export const ILogout = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M17 7l-1.4 1.4L18.2 11H8v2h10.2l-2.6 2.6L17 17l5-5zM19 19H5V5h14v2h2V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2h-2v2z" />
  );

export const ISearch = (p: React.SVGProps<SVGSVGElement>) =>
  base(
    p,
    <path d="M15.5 14h-.8l-.3-.3a6.5 6.5 0 1 0-.7.7l.3.3v.8l5 5 1.5-1.5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z" />
  );
