#include "demo.h"
#include <vector>
#include "generated.h"

// State keeps name pointers, so names taken from the text need to live on.
static const char *keep(const String &s) {
  static std::vector<char *> names;
  for (char *n : names) if (s == n) return n;
  names.push_back(strdup(s.c_str()));
  return names.back();
}

int demo_count() {
  // "WPD2 <count>" on the first line
  return atoi(DEMO_CASES + 5);
}

String load_demo_case(int index, State &state, String &title) {
  int n = demo_count();
  if (n <= 0) return "";
  index = ((index % n) + n) % n;
  String season;
  int at = -1;
  const char *p = DEMO_CASES;
  while (*p) {
    const char *e = strchr(p, '\n');
    if (!e) e = p + strlen(p);
    String line(p, e - p);
    p = *e ? e + 1 : e;
    if (line.startsWith("demo ")) {
      if (++at > index) break;
      if (at == index) title = line.substring(5);
    } else if (at == index && line.startsWith("v ")) {
      // v <name> n <number> | v <name> s <text>
      int a = line.indexOf(' ', 2), b = line.indexOf(' ', a + 1);
      if (a < 0 || b < 0) continue;
      const char *name = keep(line.substring(2, a));
      String value = line.substring(b + 1);
      if (line[a + 1] == 's') {
        state.set(name, value.c_str());
        if (!strcmp(name, "season")) season = value;
      } else {
        state.set(name, value.toDouble());
      }
    }
  }
  return season;
}
