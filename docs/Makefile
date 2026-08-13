all: rtos_plan.pdf vla_rt_review.pdf ml_rt_proposals.pdf planE_first_results.pdf
rtos_plan.pdf: rtos_plan.tex
	xelatex -interaction=nonstopmode rtos_plan.tex
	xelatex -interaction=nonstopmode rtos_plan.tex
clean:
	rm -f *.aux *.log *.out *.toc

vla_rt_review.pdf: vla_rt_review.tex
	xelatex -interaction=nonstopmode vla_rt_review.tex
	xelatex -interaction=nonstopmode vla_rt_review.tex

ml_rt_proposals.pdf: ml_rt_proposals.tex
	xelatex -interaction=nonstopmode ml_rt_proposals.tex
	xelatex -interaction=nonstopmode ml_rt_proposals.tex

planE_first_results.pdf: planE_first_results.tex
	xelatex -interaction=nonstopmode planE_first_results.tex
	xelatex -interaction=nonstopmode planE_first_results.tex
