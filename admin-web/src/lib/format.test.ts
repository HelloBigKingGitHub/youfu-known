import { describe, expect, it } from 'vitest'
import {
  formatBytes,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatRelative,
} from './format'

describe('formatNumber', () => {
  it('em-dashes nullish and NaN', () => {
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber(undefined)).toBe('—')
    expect(formatNumber(Number.NaN)).toBe('—')
  })

  it('formats integers with thousands separator', () => {
    expect(formatNumber(1234)).toBe('1,234')
    expect(formatNumber(1_000_000)).toBe('1,000,000')
  })

  it('passes through zero', () => {
    expect(formatNumber(0)).toBe('0')
  })

  it('formats negative integers', () => {
    expect(formatNumber(-1500)).toBe('-1,500')
  })
})

describe('formatPercent', () => {
  it('em-dashes nullish values', () => {
    expect(formatPercent(null)).toBe('—')
    expect(formatPercent(undefined)).toBe('—')
  })

  it('converts a fraction to a percent string', () => {
    expect(formatPercent(0.254)).toBe('25.4%')
    expect(formatPercent(1)).toBe('100.0%')
  })

  it('respects digits argument', () => {
    expect(formatPercent(0.5, 0)).toBe('50%')
  })

  it('returns NaN-safe em-dash', () => {
    expect(formatPercent(Number.NaN)).toBe('—')
  })
})

describe('formatBytes', () => {
  it('em-dashes nullish values', () => {
    expect(formatBytes(null)).toBe('—')
    expect(formatBytes(undefined)).toBe('—')
    expect(formatBytes(Number.NaN)).toBe('—')
  })

  it('formats bytes / KB / MB / GB', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.00 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.00 MB')
    expect(formatBytes(2.5 * 1024 * 1024 * 1024)).toBe('2.50 GB')
  })

  it('uses single digit when value is 10 or greater', () => {
    expect(formatBytes(15 * 1024 * 1024)).toBe('15.0 MB')
  })

  it('formats TB', () => {
    expect(formatBytes(3 * 1024 ** 4)).toBe('3.00 TB')
  })
})

describe('formatDateTime', () => {
  it('em-dashes nullish values', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime(undefined)).toBe('—')
  })

  it('returns the raw string when the value is not parseable', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
  })

  it('formats ISO strings in zh-CN locale', () => {
    const result = formatDateTime('2024-01-15T08:30:00Z')
    expect(result).toContain('2024')
    expect(result).toContain('01')
    expect(result).toContain('15')
  })
})

describe('formatRelative', () => {
  it('em-dashes nullish values', () => {
    expect(formatRelative(null)).toBe('—')
    expect(formatRelative(undefined)).toBe('—')
  })

  it('returns raw string when unparseable', () => {
    expect(formatRelative('garbage')).toBe('garbage')
  })

  it('returns 刚刚 for very recent dates', () => {
    expect(formatRelative(new Date().toISOString())).toBe('刚刚')
  })

  it('returns minutes ago for recent past dates', () => {
    const fiveMinAgo = new Date(Date.now() - 5 * 60_000).toISOString()
    expect(formatRelative(fiveMinAgo)).toBe('5 分钟前')
  })

  it('returns hours ago for dates a few hours back', () => {
    const threeHoursAgo = new Date(Date.now() - 3 * 60 * 60_000).toISOString()
    expect(formatRelative(threeHoursAgo)).toBe('3 小时前')
  })

  it('returns days ago for dates a few days back', () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60_000).toISOString()
    expect(formatRelative(twoDaysAgo)).toBe('2 天前')
  })

  it('falls back to absolute date for old entries', () => {
    const longAgo = new Date(Date.now() - 60 * 24 * 60 * 60_000).toISOString()
    const result = formatRelative(longAgo)
    expect(result).not.toBe('—')
    expect(result).toMatch(/^\d{4}[/-]\d{2}[/-]\d{2}/)
  })
})

