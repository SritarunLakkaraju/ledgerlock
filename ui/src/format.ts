// Mirrors engine/money.py::format_inr -- Indian-grouped rupee string.
export function formatInr(paise: number): string {
  const negative = paise < 0
  paise = Math.abs(Math.round(paise))
  const rupees = Math.floor(paise / 100)
  const frac = paise % 100
  const s = String(rupees)
  let grouped: string
  if (s.length <= 3) {
    grouped = s
  } else {
    const last3 = s.slice(-3)
    let rest = s.slice(0, -3)
    const parts: string[] = []
    while (rest.length > 2) {
      parts.unshift(rest.slice(-2))
      rest = rest.slice(0, -2)
    }
    if (rest) parts.unshift(rest)
    grouped = parts.join(',') + ',' + last3
  }
  const result = `₹${grouped}.${String(frac).padStart(2, '0')}`
  return negative ? `-${result}` : result
}

export function formatPct(x: number): string {
  return `${(x * 100).toFixed(1)}%`
}

export function reasonLabel(code: string): string {
  return code
    .split('_')
    .map((w) => w[0] + w.slice(1).toLowerCase())
    .join(' ')
}
