| Exit | Meaning                                                                               |
|-----:|---------------------------------------------------------------------------------------|
|    0 | Ran clean, no failures                                                                |
|    1 | Execution/oracle failure, failing replay, or failing doctor check                     |
|    2 | Invalid command, argument combination, or numeric range                               |
|    3 | Scenario import/factory problem, unreadable/malformed file, or strict replay mismatch |
|    4 | Unexpected internal CLI exception                                                     |
|  130 | KeyboardInterrupt                                                                     |