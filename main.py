# Run / Debug  BreakPoints
# Change / Edit Variables
# Add Variables

def print_hi(name,a , b):
    # Use a breakpoint in the code line below to debug your script.
    print(f'Hi, {name}')  # Press Ctrl+F8 to toggle the breakpoint.
    print(f"Sum of a and b is {a+b}")
    z = sumNum(a,b)
    print(f"Z is {z}")

def sumNum(a,b):
    print(f"Sum of a and b is {a+b}")
    return a + b

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print_hi('PyCharm')

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
