/**
 * The porch light, at title-card scale — the same glyph as
 * web/src/components/Lantern.tsx, so the cards and the app show one lantern.
 *
 * Any element with `data-lantern="<size>"` is filled in on load; add
 * `data-halo="off"` for the dim version with no glow.
 */
function porchlightLantern(size, lit) {
  const stroke = lit ? '#ffd9a0' : '#6c748c'
  const halo = lit ? '<span class="halo"></span>' : ''
  const flame = lit
    ? `<g>
         <ellipse cx="24" cy="24.4" rx="8" ry="9" fill="url(#pl-inner)"/>
         <path d="M24 17.4c2.9 2.2 4.4 4.4 4.4 6.8 0 2.7-1.9 4.7-4.4 4.7s-4.4-2-4.4-4.7c0-2.4 1.5-4.6 4.4-6.8z" fill="url(#pl-flame)"/>
         <ellipse cx="24" cy="24.8" rx="1.5" ry="2.1" fill="#fff6e2" opacity="0.9"/>
       </g>`
    : `<path d="M24 17.4c2.9 2.2 4.4 4.4 4.4 6.8 0 2.7-1.9 4.7-4.4 4.7s-4.4-2-4.4-4.7c0-2.4 1.5-4.6 4.4-6.8z" fill="#5b6480" opacity="0.5"/>`

  return `${halo}<svg viewBox="0 0 48 48" width="${size}" height="${size}" fill="none">
    <defs>
      <linearGradient id="pl-flame" x1="24" y1="18" x2="24" y2="30" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#fff3d6"/><stop offset="0.45" stop-color="#ffb347"/><stop offset="1" stop-color="#f59e0b"/>
      </linearGradient>
      <radialGradient id="pl-inner" cx="0.5" cy="0.42" r="0.6">
        <stop offset="0" stop-color="#ffb347" stop-opacity="0.55"/><stop offset="1" stop-color="#ffb347" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <g stroke="${stroke}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" opacity="${lit ? 0.95 : 0.65}">
      <path d="M24 3.5v3.2"/>
      <path d="M18.6 12.4 20.4 8.2h7.2l1.8 4.2"/>
      <path d="M15.4 12.4h17.2"/>
      <path d="M17 12.4h14l1.4 20.2a2.2 2.2 0 0 1-2.2 2.4H17.8a2.2 2.2 0 0 1-2.2-2.4z"/>
      <path d="M14.6 35h18.8l-1.3 3.4H15.9z"/>
    </g>
    <g stroke="${stroke}" stroke-width="0.9" opacity="${lit ? 0.35 : 0.28}">
      <path d="M20.6 13.4 19.9 34"/><path d="M27.4 13.4 28.1 34"/>
    </g>
    ${flame}
  </svg>`
}

document.querySelectorAll('[data-lantern]').forEach((node, index) => {
  const size = Number(node.getAttribute('data-lantern')) || 120
  const lit = node.getAttribute('data-lit') !== 'off'
  node.classList.add('lantern')
  node.innerHTML = porchlightLantern(size, lit)
  // Two lanterns on one card would collide on the gradient ids; only the first
  // card ever needs more than one, so keep them unique the cheap way.
  if (index > 0) {
    node.innerHTML = node.innerHTML
      .replaceAll('pl-flame', `pl-flame-${index}`)
      .replaceAll('pl-inner', `pl-inner-${index}`)
  }
})
