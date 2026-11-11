#include "rules.h"
#include <math.h>

#define LOG Serial1

static std::vector<String> split_tokens(const String &s) {
  std::vector<String> out;
  int i = 0, n = s.length();
  while (i < n) {
    while (i < n && s[i] == ' ') ++i;
    int j = i;
    while (j < n && s[j] != ' ') ++j;
    if (j > i) out.push_back(s.substring(i, j));
    i = j;
  }
  return out;
}

bool parse_scene(const String &text, Scene &sc) {
  sc.layers.clear();
  SceneLayer cur;
  bool in_layer = false;
  int pos = 0;
  while (pos < (int)text.length()) {
    int end = text.indexOf('\n', pos);
    if (end < 0) end = text.length();
    String line = text.substring(pos, end);
    pos = end + 1;
    line.trim();
    if (!line.length()) continue;
    std::vector<String> t = split_tokens(line);
    const String &k = t[0];
    if (k == "WPS1") continue;
    if (k == "canvas" && t.size() >= 3) { sc.width = t[1].toInt(); sc.height = t[2].toInt(); }
    else if (k == "background" && t.size() >= 4) for (int i = 0; i < 3; ++i) sc.background[i] = t[i + 1].toInt();
    else if (k == "inks" && t.size() >= 19) for (int i = 0; i < 18; ++i) sc.inks[i / 3][i % 3] = t[i + 1].toInt();
    else if (k == "tone" && t.size() >= 5) for (int i = 0; i < 4; ++i) sc.tone[i] = t[i + 1].toInt();
    else if (k == "layer" && t.size() >= 6) {
      cur = SceneLayer();
      cur.id = t[1]; cur.blend = t[2].toInt(); cur.steps = t[3].toInt();
      cur.feather = t[4].toInt(); cur.has_growth = t[5].toInt() != 0;
      in_layer = true;
    } else if (in_layer && k == "file" && t.size() >= 2) cur.file = t[1];
    else if (in_layer && k == "stage" && t.size() >= 3) cur.stages.push_back({t[1].toDouble(), t[2]});
    else if (in_layer && (k == "when" || k == "amount" || k == "opacity")) {
      std::vector<String> toks(t.begin() + 1, t.end());
      if (k == "when") cur.when = toks; else if (k == "amount") cur.amount = toks; else cur.opacity = toks;
    } else if (in_layer && k == "end") { sc.layers.push_back(cur); in_layer = false; }
  }
  return !sc.layers.empty();
}

// --- the stack machine (eval_tokens in rules.py) -------------------------------

struct Val {
  bool is_text = false;
  double n = 0;
  String s;
};

static bool truthy(const Val &v) { return v.is_text ? v.s.length() > 0 : v.n != 0; }
static Val num(double x) { Val v; v.n = x; return v; }

static double ramp(double x, double lo, double hi) {
  if (hi == lo) return x >= hi ? 1.0 : 0.0;
  return fmax(0.0, fmin(1.0, (x - lo) / (hi - lo)));
}

static Val eval_tokens(const std::vector<String> &tokens, const State &state, bool &ok) {
  std::vector<Val> st;
  st.reserve(16);
  ok = true;
  for (const String &t : tokens) {
    char kind = t[0];
    String arg = t.substring(2);
    if (kind == 'n') st.push_back(num(arg.toDouble()));
    else if (kind == 's') { Val v; v.is_text = true; v.s = arg; st.push_back(v); }
    else if (kind == 'v') {
      const StateValue *sv = state.get(arg.c_str());
      if (!sv) { LOG.printf("[rules] unknown name %s\n", arg.c_str()); ok = false; return num(0); }
      Val v; v.is_text = sv->is_text; v.n = sv->num; v.s = sv->text; st.push_back(v);
    } else if (kind == 'f') {
      int colon = arg.lastIndexOf(':');
      String name = arg.substring(0, colon);
      int argc = arg.substring(colon + 1).toInt();
      if ((int)st.size() < argc) { ok = false; return num(0); }
      double a[4] = {0, 0, 0, 0};
      for (int i = 0; i < argc && i < 4; ++i) a[i] = st[st.size() - argc + i].n;
      st.resize(st.size() - argc);
      double r = 0;
      if (name == "ramp") r = ramp(a[0], a[1], a[2]);
      else if (name == "clamp") r = fmax(argc > 1 ? a[1] : 0.0, fmin(argc > 2 ? a[2] : 1.0, a[0]));
      else if (name == "min") { r = a[0]; for (int i = 1; i < argc; ++i) r = fmin(r, a[i]); }
      else if (name == "max") { r = a[0]; for (int i = 1; i < argc; ++i) r = fmax(r, a[i]); }
      else if (name == "abs") r = fabs(a[0]);
      else if (name == "round") { double m = argc > 1 ? pow(10.0, a[1]) : 1.0; r = rint(a[0] * m) / m; }
      st.push_back(num(r));
    } else {   // 'o'
      if (arg == "not") { Val v = st.back(); st.pop_back(); st.push_back(num(truthy(v) ? 0 : 1)); continue; }
      if (arg == "neg") { st.back().n = -st.back().n; continue; }
      if (arg == "if") {
        Val other = st.back(); st.pop_back();
        Val then = st.back(); st.pop_back();
        Val test = st.back(); st.pop_back();
        st.push_back(truthy(test) ? then : other);
        continue;
      }
      Val b = st.back(); st.pop_back();
      Val a = st.back(); st.pop_back();
      double r = 0;
      if (arg == "and") r = truthy(a) && truthy(b);
      else if (arg == "or") r = truthy(a) || truthy(b);
      else if (arg == "==" || arg == "!=") {
        bool eq = a.is_text == b.is_text && (a.is_text ? a.s == b.s : a.n == b.n);
        r = (arg == "==") ? eq : !eq;
      } else if (arg == "<") r = a.n < b.n;
      else if (arg == "<=") r = a.n <= b.n;
      else if (arg == ">") r = a.n > b.n;
      else if (arg == ">=") r = a.n >= b.n;
      else if (arg == "+") r = a.n + b.n;
      else if (arg == "-") r = a.n - b.n;
      else if (arg == "*") r = a.n * b.n;
      else if (arg == "/") r = b.n ? a.n / b.n : 0;
      else if (arg == "%") r = b.n ? fmod(a.n, b.n) + ((fmod(a.n, b.n) != 0 && (b.n < 0) != (fmod(a.n, b.n) < 0)) ? b.n : 0) : 0;
      st.push_back(num(r));
    }
  }
  if (st.empty()) { ok = false; return num(0); }
  return st.back();
}

static double quantize(double x, int steps) {
  x = fmax(0.0, fmin(1.0, x));
  return steps ? rint(x * steps) / steps : x;
}

std::vector<Decision> decide(const Scene &sc, const State &state) {
  std::vector<Decision> out;
  for (const SceneLayer &L : sc.layers) {
    bool ok;
    if (!truthy(eval_tokens(L.when, state, ok)) || !ok) continue;
    double amount = quantize(eval_tokens(L.amount, state, ok).n, L.steps);
    double opacity = quantize(eval_tokens(L.opacity, state, ok).n, L.steps);
    if (amount <= 0 || opacity <= 0) continue;
    String file = L.file;
    if (!L.stages.empty()) {
      file = "";
      for (auto &st : L.stages) if (amount >= st.first) file = st.second;
      if (!file.length()) continue;
    }
    Decision d;
    d.id = L.id;
    d.file = file;
    d.amount = (uint16_t)lrint((L.has_growth ? amount : 1.0) * 65535.0);
    d.opacity = (uint8_t)lrint(opacity * 255.0);
    d.blend = L.blend;
    d.feather = L.feather;
    out.push_back(d);
  }
  return out;
}
