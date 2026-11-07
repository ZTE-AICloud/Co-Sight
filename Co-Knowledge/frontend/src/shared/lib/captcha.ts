export function generateNumericCaptcha(length = 4): string {
  const max = 10 ** length
  return Math.floor(Math.random() * max).toString().padStart(length, '0')
}
