all: rtos_plan.pdf vla_rt_review.pdf
rtos_plan.pdf: rtos_plan.tex
	xelatex -interaction=nonstopmode rtos_plan.tex
	xelatex -interaction=nonstopmode rtos_plan.tex
clean:
	rm -f *.aux *.log *.out *.toc

vla_rt_review.pdf: vla_rt_review.tex
	xelatex -interaction=nonstopmode vla_rt_review.tex
	xelatex -interaction=nonstopmode vla_rt_review.tex
