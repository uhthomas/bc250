bc250_policy_resume = 0xe022ca;
SECTIONS {
  .policy_hook 0xe022c6 : { *(.policy_hook) }
  .policy_cave 0xe19100 : { *(.policy_cave) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
}
