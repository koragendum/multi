from objects import *
import threading
import sys

class CodeHistoryElement:
    def __init__(self, line):
        # varName: currentIndex
        self.var_history_indexes = {}
        self.prophecies = []
        self.pending_forks = []
        self.pending_dbgs = []
        self.line = line

    def __str__(self):
        return f"CodeHistoryElem<\nVar History Indexes: {self.var_history_indexes},\nProphecies: {[str(proph) for proph in self.prophecies]},\nPending Forks: {self.pending_forks}>"

class VarHistoryElement:
    def __init__(self, expression, code_index):
        self.expression = expression
        self.code_index = code_index

    def __str__(self):
        return f"VarHistoryElem<Expression: {self.expression}, Code Index: {self.code_index}>"

class Environment:
    def __init__(self, var_count, verbose=False):
        # If idx = var_count[var] - 1, then var@idx is the last value of var.
        # The var_count dict is never mutated.
        self.var_histories = {}
        self.code_history = []
        self.var_count = var_count
        self.verbose = verbose

    def fork(self, var_name, var_index, new_value, universe, line_number):
        if var_name not in self.var_histories or var_index < 0:
            # Signals to caller that fork insta-dies because it's going to an undefined point.
            if self.verbose:
                sys.stderr.write(f"dbg(u:{universe},l:{line_number}): Fork happens before big-bang, travel will fail.\n")
            return None, None, None
        assert var_index < len(self.var_histories[var_name]), "Trying to fork to future event."
        code_index = self.var_histories[var_name][var_index].code_index
        assert code_index < len(self.code_history)

        new_env = Environment(self.var_count, self.verbose)
        new_env.code_history = self.code_history[:code_index + 1]
        code = self.code_history[code_index]
        new_env.var_histories = {
            var: history[:code.var_history_indexes[var] + 1] for var, history in self.var_histories.items() if var in code.var_history_indexes}
        old_var_history = new_env.var_histories[var_name][var_index]
        new_env.var_histories[var_name][var_index] = VarHistoryElement(new_value, old_var_history.code_index)
        return new_env, code_index, code.line

    def __str__(self):
        def str_var_histories(var_histories):
            return f"{{{",\n   ".join(f"{var}:\t[{",".join(str(elm) for elm in hist)}]" for var, hist in var_histories.items())}}}"
        return f"Environment:\n" + \
            f"Variable Histories:\n  {str_var_histories(self.var_histories)}\n" + \
            f"Code History:\n  [{",\n   ".join(str(elem) for elem in self.code_history)}]"

MAX_SPAWN = 10024
total_spawned = 0

def run(*args, **kwargs):
    global total_spawned
    total_spawned = 1
    outputs = {}
    run_code_to_completion(*args, outputs, **kwargs)
    for _, msgs in outputs.items():
        for msg in msgs:
            print(msg)

def run_code_to_completion(*args, **kwargs):
    threads = []
    try:
        run_code(*args, spawned_threads=threads, **kwargs)
    finally:
        for thread in threads:
            thread.join()

def run_code(code, env, universe_outputs, spawned_threads, start_index=0, universe="root", out_name="out", dbg_name="dbg"):
    global total_spawned

    spawn_count = 0
    def resolve_prophecies_and_pending_forks(prev_code, next_code):
        # Copy prophecies, but also try to resolve them.
        for prophecy in prev_code.prophecies:
            var, expression, line = prophecy
            prophecy_value = expression.eval(env)
            if prophecy_value is not None and var.name in env.var_histories and len(env.var_histories[var.name]) > var.index:
                future_value = env.var_histories[var.name][var.index].expression.eval(env)
                if future_value is not None:
                    if future_value != prophecy_value:
                        if env.verbose:
                            sys.stderr.write(f"dbg(u:{universe},l:{line}): Prophecy violated: ({var.name}@{var.index} = {future_value}) ≠ {prophecy_value}\n")
                        return False
                    continue
            if next_code is not None:
                next_code.prophecies.append((var, prophecy_value or expression, line))

        # Check if any pending forks can be executed, or copy forward to try later.
        for fork in prev_code.pending_forks:
            fork_value = fork.right.eval(env)
            if fork_value is not None:
                new_env, code_index, fork_line = env.fork(fork.left.name, fork.left.index, fork_value, universe, fork.line)

                # Premature death of fork if `new_env` is None.
                if new_env is not None:
                    if total_spawned >= MAX_SPAWN:
                        print('spawn limit reached', file=sys.stderr)
                    else:
                        args = (code, new_env, universe_outputs)
                        kwargs = {"start_index": code_index+1, "universe": f"{universe}-{spawn_count}", "out_name": out_name, "dbg_name": dbg_name}
                        thread = threading.Thread(target=run_code_to_completion, args=args, kwargs=kwargs)
                        if env.verbose:
                            sys.stderr.write(f"dbg(u:{universe},l:{fork.line}): Forking to {universe}-{spawn_count} at line {fork_line}, {fork.left.name}@{fork.left.index} = {fork_value}\n")
                        spawned_threads.append(thread)
                        thread.start()
                        spawn_count += 1
                        total_spawned += 1
            elif next_code is not None:
                next_code.pending_forks.append(fork)

        # Print any pending debug statements that may have been resolved.
        #
        for dbg in prev_code.pending_dbgs:
            val = dbg[1].eval(env)
            if val is None:
                if next_code is not None:
                    next_code.pending_dbgs.append(dbg)
            else:
                prefix = f"dbg(u:{universe},l:{dbg[0]}): " if env.verbose else ""
                sys.stderr.write(f"{prefix}now known: {str(dbg[1])} = {str(val)}\n")

        return True

    for i, stmt in enumerate(code[start_index:]):
        next_code_history = CodeHistoryElement(stmt.line)

        # Important that pending forks and prophecies get resolved before
        # executing the stmt, otherwise a fork that breaks a prophecy would not
        # get caught.
        if len(env.code_history) != 0:
            if not resolve_prophecies_and_pending_forks(env.code_history[-1], next_code_history):
                return

        match stmt.kind:
            case Assignment.MUTATION:
                assert (stmt.left.name not in env.var_histories and stmt.left.index == 0) or \
                    (stmt.left.name in env.var_histories and len(env.var_histories[stmt.left.name]) == stmt.left.index), \
                    "Mutation to event in wrong timeline position."

                val = stmt.right.eval(env)
                if stmt.left.name == dbg_name:
                    prefix = f"dbg(u:{universe},l:{stmt.line}): " if env.verbose else ""
                    if val is None:
                        next_code_history.pending_dbgs.append((stmt.line, stmt.right))
                        sys.stderr.write(f"{prefix}{str(stmt.right)} = unknown\n")
                    else:
                        output = str(val) if str(stmt.right) == str(val) else f"{str(stmt.right)} = {str(val)}"
                        sys.stderr.write(f"{prefix}{output}\n")

                if val is not None and not val.defined(env):
                    val = None
                if stmt.left.index == 0:
                    env.var_histories[stmt.left.name] = [VarHistoryElement(val or stmt.right, len(env.code_history))]
                else:
                    # Try to eval lhs. If it can't be evaluated then just take it as is.
                    env.var_histories[stmt.left.name].append(VarHistoryElement(val or stmt.right, i+start_index))
            case Assignment.REVISION:
                assert stmt.left.index < len(env.var_histories[stmt.left.name]), "Revision to event in the future."

                fork_value = stmt.right.eval(env)
                if fork_value is None:
                    next_code_history.pending_forks.append(stmt)
                else:
                    new_env, code_index, fork_line = env.fork(stmt.left.name, stmt.left.index, stmt.right.eval(env), universe, stmt.line)

                    # Premature death of fork if `new_env` is None.
                    if new_env is not None:
                        if total_spawned >= MAX_SPAWN:
                            print('spawn limit reached', file=sys.stderr)
                        else:
                            args = (code, new_env, universe_outputs)
                            kwargs = {"start_index": code_index+1, "universe": f"{universe}-{spawn_count}", "out_name": out_name, "dbg_name": dbg_name}
                            if env.verbose:
                                sys.stderr.write(f"dbg(u:{universe},l:{stmt.line}): Forking to {universe}-{spawn_count} at line {fork_line}, {stmt.left.name}@{stmt.left.index} = {fork_value}\n")
                            spawned_threads.append(threading.Thread(target=run_code_to_completion, args=args, kwargs=kwargs))
                            spawned_threads[-1].start()
                            spawn_count += 1
                            total_spawned += 1
            case Assignment.PROPHECY:
                assert stmt.left.name not in env.var_histories or len(env.var_histories[stmt.left.name]) <= stmt.left.index, \
                    "Prophecy about event in the past."
                next_code_history.prophecies.append((stmt.left, stmt.right.eval(env) or stmt.right, stmt.line))
            case _:
                assert False, "Invalid stmt kind."

        # Now go and store all the current indexes
        for var in env.var_histories:
            next_code_history.var_history_indexes[var] = len(env.var_histories[var]) - 1
        env.code_history.append(next_code_history)

    # Try one more time to resolve prophecies and pending forks.
    if len(env.code_history) != 0:
        if not resolve_prophecies_and_pending_forks(env.code_history[-1], None):
            return

    # TODO: if something in the output is indeterminate, fail this universe.
    if out_name in env.var_histories:
        outputs = [out.expression.eval(env) for out in env.var_histories[out_name]]
        for i, output in enumerate(outputs):
            if output is None or not output.defined(env):
                out = env.var_histories[out_name][i]
                if env.verbose:
                    sys.stderr.write(f"dbg(u:{universe},l:{stmt.line+1}): Indeterminate output at line {env.code_history[out.code_index].line}: {out.expression}, universe {universe} failed.\n")
                return
        universe_outputs[universe] = [str(out) for out in outputs]

if __name__ == "__main__":
    # x = 1
    # x:+1 = 2
    # x = 2
    # x:0 = 3
    code = [
        Assignment(Variable("x", 0), Literal(1, "int"), Assignment.MUTATION),
        Assignment(Variable("x", 1), Literal(2, "int"), Assignment.PROPHECY),
        Assignment(Variable("x", 1), Literal(2, "int"), Assignment.MUTATION),
        Assignment(Variable("x", 1), Literal(3, "int"), Assignment.REVISION)
    ]

    # x = 1
    # x:+1 = y:+1
    # z = 2
    # x = 2
    # y = z
    # z:0 = 3
    code = [
        Assignment(Variable("x", 0), Literal(1, "int"), Assignment.MUTATION, 1),
        Assignment(Variable("x", 1), Variable("y", 0), Assignment.PROPHECY, 2),
        Assignment(Variable("dbg", 0), Literal(1, "int"), Assignment.MUTATION, 4),
        Assignment(Variable("dbg", 1), Variable("y", 0), Assignment.MUTATION, 5),
        Assignment(Variable("dbg", 2), Variable("x", 0), Assignment.MUTATION, 6),
        Assignment(Variable("z", 0), Literal(2, "int"), Assignment.MUTATION, 8),
        Assignment(Variable("dbg", 3), Variable("y", 0), Assignment.MUTATION, 10),
        Assignment(Variable("dbg", 4), Variable("z", 10), Assignment.MUTATION, 11),
        Assignment(Variable("x", 1), Literal(2, "int"), Assignment.MUTATION, 13),
        Assignment(Variable("y", 0), Variable("z", 0), Assignment.MUTATION, 14),
        Assignment(Variable("z", 0), Literal(3, "int"), Assignment.REVISION, 15),
        Assignment(Variable("out", 0), Variable("z", 0), Assignment.MUTATION, 17),
        Assignment(Variable("out", 1), Variable("z", 1), Assignment.MUTATION, 18)
    ]
    output={}
    var_count = {"x": 2, "y": 1, "z": 1, "out": 2, "dbg": 5}
    run_code_to_completion(code, Environment(var_count), output)
    for _, outputs in output.items():
        for out in outputs:
            print(out)
