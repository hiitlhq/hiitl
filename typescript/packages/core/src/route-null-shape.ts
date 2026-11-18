/** Generated from routes.md JSON schema by tests/conformance/typed_members/generate.mjs. Source hashes: {"docs/specs/routes.md":"88441a1a0df284ad77a9538d181c399193d65b8501cc482db1fb82b3092ee298","docs/specs/envelope_schema.json":"4b6d164f63c480f76ddbeba31ab2080f278d3ea80f99408241b8cca871a49c0a"} */
export const ROUTE_NULL_SHAPE = {
  "allows_null": false,
  "properties": {
    "name": {
      "allows_null": false
    },
    "version": {
      "allows_null": false
    },
    "description": {
      "allows_null": false
    },
    "direction": {
      "allows_null": false
    },
    "timing": {
      "allows_null": false
    },
    "purpose": {
      "allows_null": false,
      "items": {
        "allows_null": false
      }
    },
    "scope": {
      "allows_null": false,
      "properties": {
        "org_id": {
          "allows_null": false
        },
        "environment": {
          "allows_null": false
        }
      }
    },
    "endpoint": {
      "allows_null": false
    },
    "auth": {
      "allows_null": false,
      "properties": {
        "type": {
          "allows_null": false
        },
        "header": {
          "allows_null": false
        },
        "secret_ref": {
          "allows_null": false
        },
        "hmac_header": {
          "allows_null": false
        }
      }
    },
    "protocol": {
      "allows_null": false
    },
    "context": {
      "allows_null": false,
      "properties": {
        "fields": {
          "allows_null": false,
          "items": {
            "allows_null": false,
            "properties": {
              "field_path": {
                "allows_null": false
              },
              "label": {
                "allows_null": false
              },
              "format": {
                "allows_null": false
              }
            }
          }
        },
        "include_policy_ref": {
          "allows_null": false
        },
        "include_audit_context": {
          "allows_null": false
        },
        "risk_framing": {
          "allows_null": false,
          "properties": {
            "severity": {
              "allows_null": false
            },
            "summary": {
              "allows_null": false
            },
            "consequences": {
              "allows_null": false,
              "properties": {
                "if_approved": {
                  "allows_null": false
                },
                "if_denied": {
                  "allows_null": false
                }
              }
            }
          }
        }
      }
    },
    "filters": {
      "allows_null": false,
      "properties": {
        "decisions": {
          "allows_null": false,
          "items": {
            "allows_null": false
          }
        },
        "actions": {
          "allows_null": false,
          "items": {
            "allows_null": false
          }
        },
        "agents": {
          "allows_null": false,
          "items": {
            "allows_null": false
          }
        },
        "sensitivity": {
          "allows_null": false,
          "items": {
            "allows_null": false
          }
        }
      }
    },
    "retry": {
      "allows_null": false,
      "properties": {
        "max_attempts": {
          "allows_null": false
        },
        "backoff": {
          "allows_null": false
        },
        "initial_delay_ms": {
          "allows_null": false
        }
      }
    },
    "queue": {
      "allows_null": false,
      "properties": {
        "batch_size": {
          "allows_null": false
        },
        "flush_interval": {
          "allows_null": false
        }
      }
    },
    "response_schema": {
      "allows_null": false,
      "properties": {
        "decision_options": {
          "allows_null": false,
          "items": {
            "allows_null": false
          }
        },
        "required_fields": {
          "allows_null": false,
          "items": {
            "allows_null": false
          }
        },
        "optional_fields": {
          "allows_null": false,
          "items": {
            "allows_null": false
          }
        },
        "reason_required_for": {
          "allows_null": false,
          "items": {
            "allows_null": false
          }
        },
        "modify_constraints": {
          "allows_null": false,
          "items": {
            "allows_null": false,
            "properties": {
              "field_path": {
                "allows_null": false
              },
              "constraint": {
                "allows_null": false
              },
              "options": {
                "allows_null": false
              }
            }
          }
        }
      }
    },
    "sla": {
      "allows_null": false,
      "properties": {
        "timeout": {
          "allows_null": false
        },
        "timeout_action": {
          "allows_null": false
        }
      }
    },
    "escalation_ladder": {
      "allows_null": false,
      "properties": {
        "levels": {
          "allows_null": false,
          "items": {
            "allows_null": false,
            "properties": {
              "level": {
                "allows_null": false
              },
              "route": {
                "allows_null": false
              },
              "after": {
                "allows_null": false
              }
            }
          }
        },
        "max_escalation_depth": {
          "allows_null": false
        },
        "final_timeout_action": {
          "allows_null": false
        }
      }
    },
    "correlation": {
      "allows_null": false,
      "properties": {
        "token_field": {
          "allows_null": false
        }
      }
    },
    "inbound": {
      "allows_null": false,
      "properties": {
        "url": {
          "allows_null": false
        },
        "auth": {
          "allows_null": false,
          "properties": {
            "type": {
              "allows_null": false
            },
            "token_ref": {
              "allows_null": false
            }
          }
        },
        "payload_mapping": {
          "allows_null": false,
          "properties": {
            "signal_type": {
              "allows_null": false
            },
            "agent_ref": {
              "allows_null": false
            },
            "severity": {
              "allows_null": false
            },
            "metadata": {
              "allows_null": false,
              "additionalProperties": {
                "allows_null": false
              }
            }
          }
        },
        "permissions": {
          "allows_null": false,
          "properties": {
            "can_enforce": {
              "allows_null": false
            },
            "can_propose": {
              "allows_null": false
            },
            "can_signal": {
              "allows_null": false
            },
            "enforce_scope": {
              "allows_null": false,
              "items": {
                "allows_null": false
              }
            }
          }
        },
        "acceptance_mode": {
          "allows_null": false
        }
      }
    },
    "metadata": {
      "allows_null": false,
      "properties": {
        "author": {
          "allows_null": false
        },
        "created_at": {
          "allows_null": false
        },
        "tags": {
          "allows_null": false,
          "items": {
            "allows_null": false
          }
        }
      }
    }
  }
} as const;
