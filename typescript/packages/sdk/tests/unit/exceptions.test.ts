/**
 * Tests for HIITL SDK exceptions.
 */

import { describe, it, expect } from 'vitest';
import {
  HIITLError,
  PolicyLoadError,
  AuditLogError,
  ConfigurationError,
  EnvelopeValidationError,
} from '../../src/exceptions.js';

describe('Exceptions', () => {
  describe('HIITLError', () => {
    it('should create error with message', () => {
      const error = new HIITLError('Test error message');

      expect(error).toBeInstanceOf(Error);
      expect(error).toBeInstanceOf(HIITLError);
      expect(error.message).toBe('Test error message');
      expect(error.name).toBe('HIITLError');
    });

    it('should have stack trace', () => {
      const error = new HIITLError('Test error');

      expect(error.stack).toBeDefined();
      expect(error.stack).toContain('HIITLError');
    });
  });

  describe('PolicyLoadError', () => {
    it('should extend HIITLError', () => {
      const error = new PolicyLoadError('Policy file not found');

      expect(error).toBeInstanceOf(Error);
      expect(error).toBeInstanceOf(HIITLError);
      expect(error).toBeInstanceOf(PolicyLoadError);
      expect(error.name).toBe('PolicyLoadError');
    });

    it('should preserve message', () => {
      const message = 'Invalid policy syntax: missing field "rules"';
      const error = new PolicyLoadError(message);

      expect(error.message).toBe(message);
    });
  });

  describe('AuditLogError', () => {
    it('should extend HIITLError', () => {
      const error = new AuditLogError('Cannot write to database');

      expect(error).toBeInstanceOf(Error);
      expect(error).toBeInstanceOf(HIITLError);
      expect(error).toBeInstanceOf(AuditLogError);
      expect(error.name).toBe('AuditLogError');
    });
  });

  describe('ConfigurationError', () => {
    it('should extend HIITLError', () => {
      const error = new ConfigurationError('Missing required field: org_id');

      expect(error).toBeInstanceOf(Error);
      expect(error).toBeInstanceOf(HIITLError);
      expect(error).toBeInstanceOf(ConfigurationError);
      expect(error.name).toBe('ConfigurationError');
    });
  });

  describe('EnvelopeValidationError', () => {
    it('should extend HIITLError', () => {
      const error = new EnvelopeValidationError('Envelope validation failed');

      expect(error).toBeInstanceOf(Error);
      expect(error).toBeInstanceOf(HIITLError);
      expect(error).toBeInstanceOf(EnvelopeValidationError);
      expect(error.name).toBe('EnvelopeValidationError');
    });

    it('should store validation errors', () => {
      const validationErrors = [
        'target: Required',
        'parameters.amount: Expected number, received string',
      ];
      const error = new EnvelopeValidationError(
        'Validation failed',
        validationErrors
      );

      expect(error.validation_errors).toEqual(validationErrors);
    });

    it('should default to empty array for validation errors', () => {
      const error = new EnvelopeValidationError('Validation failed');

      expect(error.validation_errors).toEqual([]);
    });
  });

  describe('Error catching', () => {
    it('should catch all SDK errors with HIITLError', () => {
      const errors = [
        new HIITLError('Base error'),
        new PolicyLoadError('Policy error'),
        new AuditLogError('Audit error'),
        new ConfigurationError('Config error'),
        new EnvelopeValidationError('Validation error'),
      ];

      for (const error of errors) {
        expect(error).toBeInstanceOf(HIITLError);
      }
    });
  });
});
