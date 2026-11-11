// The "world state" the scene rules read: name -> number or text.
// Same names and meanings as painter/weather.py's build_state().
#pragma once
#include <Arduino.h>

struct StateValue {
  const char *name;
  bool is_text;
  double num;
  String text;
};

class State {
 public:
  static const int MAX = 40;
  void set(const char *name, double v) { slot(name).is_text = false; slot(name).num = v; }
  void set(const char *name, bool v) { set(name, v ? 1.0 : 0.0); }
  void set(const char *name, int v) { set(name, (double)v); }
  void set(const char *name, const char *v) { StateValue &s = slot(name); s.is_text = true; s.text = v; }
  const StateValue *get(const char *name) const {
    for (int i = 0; i < n; ++i) if (!strcmp(vals[i].name, name)) return &vals[i];
    return nullptr;
  }
  void print(Print &out) const {
    for (int i = 0; i < n; ++i) {
      if (vals[i].is_text) out.printf("  %-18s %s\n", vals[i].name, vals[i].text.c_str());
      else out.printf("  %-18s %g\n", vals[i].name, vals[i].num);
    }
  }

 private:
  StateValue vals[MAX];
  int n = 0;
  StateValue &slot(const char *name) {
    for (int i = 0; i < n; ++i) if (!strcmp(vals[i].name, name)) return vals[i];
    vals[n].name = name;   // names are string literals
    return vals[n++];
  }
};
