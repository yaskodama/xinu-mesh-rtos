all: rtos_plan.pdf
rtos_plan.pdf: rtos_plan.tex
	xelatex -interaction=nonstopmode rtos_plan.tex
	xelatex -interaction=nonstopmode rtos_plan.tex
clean:
	rm -f *.aux *.log *.out *.toc
