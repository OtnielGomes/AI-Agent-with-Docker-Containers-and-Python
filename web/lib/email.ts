const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function isValidEmail(address: string): boolean {
  if (!address || !address.trim()) {
    return false;
  }
  return EMAIL_PATTERN.test(address.trim());
}
