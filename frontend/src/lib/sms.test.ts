import { describe, it, expect } from 'vitest';
import { isGsm7, smsInfo, smsSegments } from './sms';

describe('SMS segment counter', () => {
  it('empty text is zero segments', () => {
    expect(smsSegments('')).toBe(0);
  });

  describe('GSM-7', () => {
    it('detects plain Latin text as GSM-7', () => {
      expect(isGsm7('Koshi rising at Chatara. Move to shelter.')).toBe(true);
    });
    it('fits 160 characters in one segment', () => {
      expect(smsInfo('a'.repeat(160))).toMatchObject({ encoding: 'GSM-7', segments: 1, remaining: 0 });
    });
    it('uses 153 per segment when concatenated', () => {
      expect(smsSegments('a'.repeat(161))).toBe(2);
      expect(smsSegments('a'.repeat(306))).toBe(2);
      expect(smsSegments('a'.repeat(307))).toBe(3);
      expect(smsSegments('a'.repeat(459))).toBe(3);
      expect(smsSegments('a'.repeat(460))).toBe(4);
    });
    it('counts extension characters as two septets', () => {
      expect(smsInfo('€'.repeat(80))).toMatchObject({ encoding: 'GSM-7', units: 160, segments: 1 });
      expect(smsInfo(`${'a'.repeat(159)}€`)).toMatchObject({ units: 161, segments: 2 });
    });
  });

  describe('UCS-2', () => {
    it('switches to UCS-2 for Devanagari', () => {
      expect(isGsm7('कोसी नदी')).toBe(false);
      expect(smsInfo('कोसी नदी').encoding).toBe('UCS-2');
    });
    it('fits 70 characters in one segment', () => {
      expect(smsInfo('क'.repeat(70))).toMatchObject({ encoding: 'UCS-2', segments: 1 });
    });
    it('uses 67 per segment when concatenated', () => {
      expect(smsSegments('क'.repeat(71))).toBe(2);
      expect(smsSegments('क'.repeat(134))).toBe(2);
      expect(smsSegments('क'.repeat(135))).toBe(3);
      expect(smsSegments('क'.repeat(201))).toBe(3);
      expect(smsSegments('क'.repeat(202))).toBe(4);
    });
    it('one non-GSM character forces UCS-2 for the whole message', () => {
      expect(smsInfo(`${'a'.repeat(69)}क`)).toMatchObject({ encoding: 'UCS-2', segments: 1 });
      expect(smsInfo(`${'a'.repeat(70)}क`)).toMatchObject({ encoding: 'UCS-2', segments: 2 });
    });
    it('counts characters outside the BMP as two UTF-16 units', () => {
      expect(smsInfo('🌊').units).toBe(2);
      expect(smsInfo('🌊').chars).toBe(1);
    });
  });
});
