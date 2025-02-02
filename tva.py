import threading

# X = K
class Assignment:
    MUTATION = 0
    REVISION = 1
    PROPHECY = 2

    def __init__(self, left, right, kind):
        self.left = left
        self.right = right
        self.kind = kind

# X or X:N
class Variable:
    def __init__(self, name, index):
        self.name = name

        # Indexes are ints. These should be absolute coming from parser.
        self.index = index

    def eval(self, env):
        if self.name in env.var_histories and self.index < len(env.var_histories[self.name]):
            return env.var_histories[self.name][self.index].expression.eval(env)
        return None
        
    def __repr__(self):
        return f"Variable(name={self.name}, index={self.index})"

# Note: code history needs to keep track of unresolved prophecies at each point
# so that forks that violate prophecies immediately die.

# add sub mul div mod
# and or
# gt lt geq leq eq neq
# idx
class BinaryExpression:
    def __init__(self, left, right, operator):
        self.left = left
        self.right = right
        self.operator = operator

    def eval(self, env):
        left = self.left.eval(env)
        right = self.right.eval(env)
        if left is None or right is None:
            return None
        match self.operator:
            case "add":
                pass
                # todo - int add or tuple concat
            case "sub":
                pass
                # todo - int sub
            case "mul":
                pass
                # todo - int mul
            case "div":
                pass
                # todo - int div
            case "mod":
                pass
                # todo - int mod
            case "and":
                pass
                # todo
            case "or":
                pass
                # todo
            case "gt":
                pass
                # todo
            case "lt":
                pass
                # todo
            case "geq":
                pass
                # todo
            case "leq":
                pass
                # todo
            case "eq":
                pass
                # todo
            case "neq":
                pass
                # todo
            case "idx":
                pass
                # todo - tuple index (left is tuple, right is int?)
            case _:
                return None


# neg not len
class UnaryExpression:
    def __init__(self, operand, operator):
        self.operand = operand

# undefined
# bool
# atom
# int
class Literal:
    def __init__(self, value, kind):
        self.value = value
        self.kind = kind

    def eval(self, env):
        return self

    def __repr__(self):
        return f"Literal(value={self.value}, kind={self.kind})"

    def __eq__(self, other):
        return isinstance(other, Literal) and self.value == other.value

class Tuple:
    def __init__(self, elements):
        self.elements = elements

    def eval(self, env):
        values = []
        for elem in self.elements:
            value = elem.eval(env)
            if value is None:
                return None
            values.append(value)
        return values

# Literal.eval(...) returns self

# eval returns a Literal or Tuple if the value is known
#   and None otherwise

class CodeHistoryElement:
    def __init__(self):
        # varName: currentIndex
        self.var_history_indexes = {}
        self.prophecies = []
        self.pending_forks = []

    def __str__(self):
        return f"CodeHistoryElem<\nVar History Indexes: {self.var_history_indexes},\nProphecies: {[str(proph) for proph in self.prophecies]},\nPending Forks: {self.pending_forks}>"

class VarHistoryElement:
    def __init__(self, expression, code_index):
        self.expression = expression
        self.code_index = code_index
        
    def __str__(self):
        return f"VarHistoryElem<Expression: {self.expression}, Code Index: {self.code_index}>"

class Environment:
    def __init__(self):
        self.var_histories = {}
        self.code_history = []

    def fork(self, var_name, var_index, new_value):
        assert var_name in self.var_histories, "Reference to past event that never occurred."
        assert var_index < len(self.var_histories[var_name]), "Trying to fork to future event."
        code_index = self.var_histories[var_name][var_index].code_index
        assert code_index < len(self.code_history)

        new_env = Environment()
        new_env.code_history = self.code_history[:code_index + 1]
        code = self.code_history[code_index]
        new_env.var_histories = {
            var: history[:code.var_history_indexes[var] + 1] for var, history in self.var_histories.items() if var in code.var_history_indexes}
        new_env.var_histories[var_name][var_index].expression = new_value
        return new_env, code_index
    
    def __str__(self):
        def str_var_histories(var_histories):
            return f"{{{",\n   ".join(f"{var}:\t[{",".join(str(elm) for elm in hist)}]" for var, hist in var_histories.items())}}}"
        return f"Environment:\n" + \
            f"Variable Histories:\n  {str_var_histories(self.var_histories)}\n" + \
            f"Code History:\n  [{",\n   ".join(str(elem) for elem in self.code_history)}]"

def run_code(code, start_index=0, env=Environment()):
    def resolve_prophecies_and_pending_forks(prev_code, next_code):
        # Copy prophecies, but also try to resolve them.
        for prophecy in prev_code.prophecies:
            var, expression = prophecy
            prophecy_value = expression.eval(env)
            if prophecy_value is not None and var.name in env.var_histories and len(env.var_histories[var.name]) > var.index:
                future_value = env.var_histories[var.name][var.index].expression.eval(env)
                if future_value is not None:
                    assert future_value == prophecy_value, "Prophecy violated."
                    continue
            if next_code is not None:
                next_code.prophecies.append((var, prophecy_value or expression))
        
        # Check if any pending forks can be executed, or copy forward to try later.
        for fork in prev_code.pending_forks:
            fork_value = fork.right.eval(env)
            if fork_value is not None:
                new_env, code_index = env.fork(fork.left.name, fork.left.index, fork_value)
                threading.Thread(target=run_code, args=(code, code_index, new_env)).start()
            elif next_code is not None:
                next_code.pending_forks.append(fork)

    for i, stmt in enumerate(code[start_index:]):
        next_code_history = CodeHistoryElement()

        # Important that pending forks and prophecies get resolved before
        # executing the stmt, otherwise a fork that breaks a prophecy would not
        # get caught.
        if len(env.code_history) != 0:
            resolve_prophecies_and_pending_forks(env.code_history[-1], next_code_history)

        match stmt.kind:
            case Assignment.MUTATION:
                assert stmt.left.index == 0 or \
                    (stmt.left.name in env.var_histories and len(env.var_histories[stmt.left.name]) == stmt.left.index), \
                    "Mutation to event in wrong timeline position."

                if stmt.left.index == 0:
                    env.var_histories[stmt.left.name] = [VarHistoryElement(stmt.right.eval(env) or stmt.right, len(env.code_history))]
                else:
                    # Try to eval lhs. If it can't be evaluated then just take it as is.
                    env.var_histories[stmt.left.name].append(VarHistoryElement(stmt.right.eval(env) or stmt.right, i+start_index))
            case Assignment.REVISION:
                assert stmt.left.index >= 0, "Revision to event before big-bang."
                assert stmt.left.name in env.var_histories, "Revision to event that never occurred."
                assert stmt.left.index < len(env.var_histories[stmt.left.name]), "Revision to event in the future."

                fork_value = stmt.right.eval(env)
                if fork_value is None:
                    next_code_history.pending_forks.append(stmt)
                else:
                    new_env, code_index = env.fork(stmt.left.name, stmt.left.index, stmt.right.eval(env))
                    threading.Thread(target=run_code, args=(code, code_index, new_env)).start()
            case Assignment.PROPHECY:
                assert stmt.left.name not in env.var_histories or len(env.var_histories[stmt.left.name]) <= stmt.left.index, \
                    "Prophecy about event in the past."
                next_code_history.prophecies.append((stmt.left, stmt.right.eval(env) or stmt))
            case _:
                assert False, "Invalid stmt kind."

        # Now go and store all the current indexes
        for var in env.var_histories:
            next_code_history.var_history_indexes[var] = len(env.var_histories[var]) - 1
        env.code_history.append(next_code_history)

    # Try one more time to resolve prophecies and pending forks.
    if len(env.code_history) != 0:
        resolve_prophecies_and_pending_forks(env.code_history[-1], None)

    print(env)

# Do parsing, and lexing, generate a list of stmts, each stmt is an AST.
#
# x = 1
# x:+1 = 2
# x = 2
# x:0 = 3
code = [
    Assignment(Variable("x", 0), Literal(1, int), Assignment.MUTATION),
    Assignment(Variable("x", 1), Literal(2, int), Assignment.PROPHECY),
    Assignment(Variable("x", 1), Literal(2, int), Assignment.MUTATION),
    Assignment(Variable("x", 1), Literal(3, int), Assignment.REVISION)]
env = Environment()
run_code(code)
