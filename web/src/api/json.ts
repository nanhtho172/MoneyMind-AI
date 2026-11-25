import { parse, stringify } from 'lossless-json'

// The parser passes the original numeric lexeme, before any rounding by Number.
export function decodeJson(text: string): unknown {
  return parse(text, undefined, (lexeme: string) => {
    if (/^-?\d+$/.test(lexeme)) return BigInt(lexeme)
    return Number(lexeme)
  })
}

export function encodeJson(value: unknown): string {
  const json = stringify(value)
  if (json === undefined) throw new TypeError('Dữ liệu không thể gửi dưới dạng JSON.')
  return json
}
