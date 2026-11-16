/** Generated from telemetry_schema.md and sync_engine.md by numeric_sync/generate.py. */
export const shapes = {
  "telemetry": {
    "type": "object",
    "required": [
      "telemetry_version",
      "window_start",
      "window_end",
      "org_id",
      "environment",
      "sdk_version",
      "sdk_language",
      "tool_summaries"
    ],
    "properties": {
      "telemetry_version": {
        "type": "string",
        "const": "2.0"
      },
      "window_start": {
        "type": "string"
      },
      "window_end": {
        "type": "string"
      },
      "org_id": {
        "type": "string"
      },
      "environment": {
        "type": "string"
      },
      "sdk_version": {
        "type": "string"
      },
      "sdk_language": {
        "type": "string"
      },
      "tool_summaries": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/tool_summary"
        }
      },
      "agent_summaries": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/agent_summary"
        }
      },
      "system_metrics": {
        "$ref": "#/$defs/system_metrics"
      }
    },
    "$defs": {
      "tool_summary": {
        "type": "object",
        "required": [
          "action",
          "action_count",
          "decision_counts"
        ],
        "properties": {
          "action": {
            "type": "string"
          },
          "action_count": {
            "type": "integer",
            "minimum": 0
          },
          "decision_counts": {
            "type": "object",
            "properties": {
              "ALLOW": {
                "type": "integer",
                "minimum": 0
              },
              "BLOCK": {
                "type": "integer",
                "minimum": 0
              },
              "REQUIRE_APPROVAL": {
                "type": "integer",
                "minimum": 0
              },
              "RATE_LIMIT": {
                "type": "integer",
                "minimum": 0
              },
              "KILL_SWITCH": {
                "type": "integer",
                "minimum": 0
              },
              "SANDBOX": {
                "type": "integer",
                "minimum": 0
              },
              "ESCALATE": {
                "type": "integer",
                "minimum": 0
              },
              "PAUSE": {
                "type": "integer",
                "minimum": 0
              },
              "ROUTE": {
                "type": "integer",
                "minimum": 0
              },
              "OBSERVE": {
                "type": "integer",
                "minimum": 0
              }
            },
            "additionalProperties": {
              "type": "integer",
              "minimum": 0
            }
          },
          "latency": {
            "$ref": "#/$defs/latency_stats"
          },
          "operations": {
            "type": "object",
            "additionalProperties": {
              "type": "integer",
              "minimum": 0
            }
          },
          "parameter_stats": {
            "type": "array",
            "items": {
              "$ref": "#/$defs/parameter_stat"
            }
          },
          "target_cardinality": {
            "type": "integer",
            "minimum": 0
          },
          "error_count": {
            "type": "integer",
            "minimum": 0
          },
          "reason_code_counts": {
            "type": "object",
            "additionalProperties": {
              "type": "integer",
              "minimum": 0
            }
          }
        }
      },
      "agent_summary": {
        "type": "object",
        "required": [
          "agent_id",
          "action_count"
        ],
        "properties": {
          "agent_id": {
            "type": "string"
          },
          "action_count": {
            "type": "integer",
            "minimum": 0
          },
          "tools_used": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "decision_counts": {
            "type": "object",
            "additionalProperties": {
              "type": "integer",
              "minimum": 0
            }
          },
          "distinct_users": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "system_metrics": {
        "type": "object",
        "properties": {
          "uptime_seconds": {
            "type": "number"
          },
          "total_evaluations": {
            "type": "integer",
            "minimum": 0
          },
          "error_counts": {
            "type": "object",
            "required": [
              "evaluation_errors",
              "telemetry_errors"
            ],
            "properties": {
              "evaluation_errors": {
                "type": "integer",
                "minimum": 0
              },
              "telemetry_errors": {
                "type": "integer",
                "minimum": 0
              }
            }
          }
        }
      },
      "latency_stats": {
        "type": "object",
        "properties": {
          "p50": {
            "type": "number"
          },
          "p95": {
            "type": "number"
          },
          "p99": {
            "type": "number"
          },
          "min": {
            "type": "number"
          },
          "max": {
            "type": "number"
          },
          "mean": {
            "type": "number"
          }
        }
      },
      "parameter_stat": {
        "type": "object",
        "required": [
          "parameter_path",
          "stat_type"
        ],
        "properties": {
          "parameter_path": {
            "type": "string"
          },
          "stat_type": {
            "type": "string"
          },
          "numeric_stats": {
            "type": "object",
            "required": [
              "count"
            ],
            "properties": {
              "count": {
                "type": "integer",
                "minimum": 0
              },
              "mean": {
                "type": "number"
              }
            }
          },
          "categorical_stats": {
            "type": "object",
            "properties": {
              "distinct_count": {
                "type": "integer",
                "minimum": 0
              }
            }
          }
        }
      }
    }
  },
  "audit_ack": {
    "type": "object",
    "required": [
      "accepted",
      "duplicates"
    ],
    "properties": {
      "accepted": {
        "type": "integer"
      },
      "duplicates": {
        "type": "integer"
      },
      "errors": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "event_id": {
              "type": "string"
            },
            "code": {
              "type": "string"
            },
            "message": {
              "type": "string"
            }
          }
        }
      }
    }
  }
};
